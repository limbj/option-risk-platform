declare module "plotly.js-dist-min" {
  const Plotly: {
    react: (
      element: HTMLElement,
      data: unknown[],
      layout: object,
      config: object,
    ) => Promise<void>;
    purge: (element: HTMLElement) => void;
  };
  export default Plotly;
}
