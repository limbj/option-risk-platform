import numpy as np

from ml.dataset import dataset_hash, labels, sample_features
from ml.features import in_heldout_region
from quant.errors import PricingError


def test_heldout_parameter_region_does_not_leak_into_training():
    train = sample_features(512, np.random.default_rng(1729))
    heldout = sample_features(128, np.random.default_rng(1730), heldout=True)
    assert not any(in_heldout_region(row.tolist()) for row in train)
    assert all(in_heldout_region(row.tolist()) for row in heldout)
    assert np.allclose(train[:, 1] * 365, np.round(train[:, 1] * 365))


def test_seed_and_dataset_digest_reproduce_the_same_samples_and_detect_changes():
    first = sample_features(20, np.random.default_rng(1729))
    second = sample_features(20, np.random.default_rng(1729))
    assert np.array_equal(first, second)
    assert dataset_hash({"train_x": first}) == dataset_hash({"train_x": second})
    second[0, 0] += 0.01
    assert dataset_hash({"train_x": first}) != dataset_hash({"train_x": second})


def test_failed_teacher_labels_are_excluded_with_the_input_and_reason_recorded():
    class Teacher:
        def price(self, contract, market):
            if market.sigma0 < 0.1:
                raise PricingError("reference integration failed")
            return 10.0

    rows = np.asarray([[0, 1, 0.03, 0.05], [0, 1, 0.03, 0.2]])
    valid, prices, failures = labels(Teacher(), rows)
    assert valid.tolist() == [[0, 1, 0.03, 0.2]]
    assert prices.tolist() == [0.1]
    assert failures == [{"features": [0, 1, 0.03, 0.05], "reason": "reference integration failed"}]
