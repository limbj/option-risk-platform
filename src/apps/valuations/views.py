import csv
import io
import json

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.model_registry.models import ModelArtifact
from apps.model_registry.reporting import artifact_document
from apps.portfolios.models import InputVersion
from apps.valuations.models import ValuationRun
from apps.valuations.reporting import input_document, run_document, run_summary
from apps.valuations.services import IdempotencyConflict, create_inputs, create_run, retry_run
from quant.errors import ContractValidationError


class StrictRequest(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"detail": "Unknown request fields"})
        return super().to_internal_value(data)


class InputRequest(StrictRequest):
    name = serializers.CharField(max_length=120)
    inputs = serializers.JSONField()


class RunRequest(StrictRequest):
    input_id = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=["REFERENCE", "COMPARE"])
    idempotency_key = serializers.CharField(max_length=128)
    artifact_id = serializers.UUIDField(required=False, allow_null=True)


def owned_run(request, run_id):
    return get_object_or_404(
        ValuationRun.objects.select_related("inputs", "artifact"), pk=run_id, owner=request.user
    )


@api_view(["GET"])
def sample(request):
    return Response(json.loads((settings.BASE_DIR / "examples" / "stage1_inputs.json").read_text()))


@api_view(["GET", "POST"])
def inputs(request):
    if request.method == "GET":
        return Response(
            {
                "items": [
                    input_document(item)
                    for item in InputVersion.objects.filter(owner=request.user).order_by(
                        "-created_at"
                    )[:100]
                ]
            }
        )
    serializer = InputRequest(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        record = create_inputs(
            request.user, serializer.validated_data["name"], serializer.validated_data["inputs"]
        )
    except (ContractValidationError, TypeError, ValueError) as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response(input_document(record), status=201)


@api_view(["GET"])
def input_detail(request, input_id):
    return Response(
        input_document(get_object_or_404(InputVersion, pk=input_id, owner=request.user))
    )


@api_view(["GET", "POST"])
def runs(request):
    if request.method == "GET":
        return Response(
            {
                "items": [
                    run_summary(run)
                    for run in ValuationRun.objects.filter(owner=request.user).select_related(
                        "inputs"
                    )[:100]
                ]
            }
        )
    serializer = RunRequest(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    record = get_object_or_404(InputVersion, pk=data["input_id"], owner=request.user)
    artifact = (
        get_object_or_404(ModelArtifact, pk=data["artifact_id"])
        if data.get("artifact_id")
        else None
    )
    try:
        run, created = create_run(
            request.user, record, data["mode"], data["idempotency_key"], artifact
        )
    except IdempotencyConflict as exc:
        return Response({"detail": str(exc)}, status=409)
    response = run_summary(run)
    response["created"] = created
    return Response(response, status=202)


@api_view(["GET"])
def run_detail(request, run_id):
    return Response(run_document(owned_run(request, run_id)))


@api_view(["POST"])
def retry(request, run_id):
    return Response(run_summary(retry_run(request.user, owned_run(request, run_id))), status=202)


@api_view(["GET"])
def export(request, run_id):
    document = run_document(owned_run(request, run_id))
    output_format = request.query_params.get("format", "json")
    if output_format == "json":
        response = HttpResponse(
            json.dumps(document, allow_nan=False, indent=2), content_type="application/json"
        )
    elif output_format == "csv":
        stream = io.StringIO(newline="")
        fields = [
            "scenario_index",
            "scenario_name",
            "position_index",
            "status",
            "reference_price",
            "reference_value",
            "error",
            "ml_price",
            "ml_value",
            "ml_error",
            "price_error",
            "sensitivities",
            "timings",
            "scenario_complete",
            "scenario_value",
            "stress_pnl",
            "ml_complete",
            "ml_total",
            "ml_stress_pnl",
            "run_id",
            "run_status",
            "provenance",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for cell in document["results"]:
            total = document["totals"][cell["scenario_index"]]
            row = dict(cell)
            row.update(
                scenario_complete=total["complete"],
                scenario_value=total["value"],
                stress_pnl=total["pnl"],
                ml_complete=total["ml_complete"],
                ml_total=total["ml_value"],
                ml_stress_pnl=total["ml_pnl"],
                run_id=document["id"],
                run_status=document["status"],
                provenance=json.dumps(document["provenance"], allow_nan=False),
                sensitivities=json.dumps(cell["sensitivities"]),
                timings=json.dumps(cell["timings"]),
            )
            # Names originate in manual/CSV input; neutralize spreadsheet formulas in exports.
            for key, value in row.items():
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    row[key] = "'" + value
            writer.writerow(row)
        response = HttpResponse(stream.getvalue(), content_type="text/csv")
    else:
        return Response({"detail": "format must be json or csv"}, status=400)
    response["Content-Disposition"] = f'attachment; filename="valuation-{run_id}.{output_format}"'
    return response


@api_view(["GET"])
def models(request):
    return Response(
        {
            "items": [
                artifact_document(item) for item in ModelArtifact.objects.order_by("-created_at")
            ]
        }
    )
