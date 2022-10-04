import pandas as pd
from credoai.artifacts import TabularData
from credoai.evaluators import Evaluator
from credoai.evaluators.utils.fairlearn import setup_metric_frames
from credoai.evaluators.utils.validation import (
    check_artifact_for_nulls,
    check_data_instance,
    check_existence,
)
from credoai.evidence import MetricContainer, TableContainer
from credoai.modules.metric_constants import (
    MODEL_METRIC_CATEGORIES,
    THRESHOLD_METRIC_CATEGORIES,
)
from credoai.modules.metrics import Metric, find_metrics
from credoai.utils import global_logger
from credoai.utils.common import ValidationError


class Performance(Evaluator):
    """
    Performance evaluator for Credo AI.

    This evaluator calculates overall performance metrics.
    Handles any metric that can be calculated on a set of ground truth labels and predictions,
    e.g., binary classification, multiclass classification, regression.

    This module takes in a set of metrics and provides functionality to:
    - calculate the metrics
    - create disaggregated metrics

    Parameters
    ----------
    metrics : List-like
        list of metric names as strings or list of Metric objects (credoai.modules.metrics.Metric).
        Metric strings should in list returned by credoai.modules.metric_utils.list_metrics().
        Note for performance parity metrics like
        "false negative rate parity" just list "false negative rate". Parity metrics
        are calculated automatically if the performance metric is supplied
    y_true : (List, pandas.Series, numpy.ndarray)
        The ground-truth labels (for classification) or target values (for regression).
    y_pred : (List, pandas.Series, numpy.ndarray)
        The predicted labels for classification
    y_prob : (List, pandas.Series, numpy.ndarray), optional
        The unthresholded predictions, confidence values or probabilities.
    """

    name = "Performance"
    required_artifacts = {"model", "assessment_data"}

    def __init__(self, metrics=None):
        super().__init__()
        # assign variables
        self.metrics = metrics
        self.metric_frames = {}
        self.performance_metrics = None
        self.prob_metrics = None
        self.failed_metrics = None
        self.perform_disaggregation = True
        # Perform_disaggregations is no longer needed?
        # Removing it might break some things, like the Quickstart.
        # Keeping for now. ESS 9/29/22

    def _setup(self):
        # data variables
        self.y_true = self.assessment_data.y
        self.y_pred = self.model.predict(self.assessment_data.X)
        try:
            self.y_prob = self.model.predict_proba(self.assessment_data.X)
        except:
            self.y_prob = None
        self.update_metrics(self.metrics)
        self.results = list()

        return self

    def evaluate(self):
        """
        Run performance base module


        Returns
        -------
        self
        """
        self._prepare_results()
        return self

    def _prepare_results(self):
        """Prepares metric results for Credo AI's governance platform

        Structures results for export as a dataframe with appropriate structure
        for exporting. See credoai.evidence.containers.

        Returns
        -------
        pd.DataFrame
        Raises
        ------
        NotRunError
            Occurs if self.run is not called yet to generate the raw assessment results
        """
        scalar_results, threshold_results = self.get_overall_metrics()

        if not scalar_results.empty:
            self.results.append(
                MetricContainer(scalar_results, **self.get_container_info())
            )
        if not threshold_results.empty:
            for _, threshold_metric in threshold_results.iterrows():
                threshold_metric.value.name = threshold_metric.threshold_metric
                self.results.append(
                    TableContainer(threshold_metric.value, **self.get_container_info())
                )

    def update_metrics(self, metrics, replace=True):
        """replace metrics

        Parameters
        ----------
        metrics : List-like
            list of metric names as string or list of Metrics (credoai.metrics.Metric).
            Metric strings should in list returned by credoai.modules.list_metrics.
            Note for performance parity metrics like
            "false negative rate parity" just list "false negative rate". Parity metrics
            are calculated automatically if the performance metric is supplied
        """
        if replace:
            self.metrics = metrics
        else:
            self.metrics += metrics
        (
            self.performance_metrics,
            self.prob_metrics,
            self.threshold_metrics,
            self.failed_metrics,
        ) = self._process_metrics(self.metrics)

        dummy_sensitive = pd.Series(["NA"] * len(self.y_true), name="NA")
        self.metric_frames = setup_metric_frames(
            self.performance_metrics,
            self.prob_metrics,
            self.threshold_metrics,
            self.y_pred,
            self.y_prob,
            self.y_true,
            dummy_sensitive,
        )

    def get_df(self):
        """Return dataframe of input arrays

        Returns
        -------
        pandas.DataFrame
            Dataframe containing the input arrays
        """
        df = pd.DataFrame({"true": self.y_true, "pred": self.y_pred})
        if self.y_prob is not None:
            y_prob_df = pd.DataFrame(self.y_prob)
            y_prob_df.columns = [f"y_prob_{i}" for i in range(y_prob_df.shape[1])]
            df = pd.concat([df, y_prob_df], axis=1)

        return df

    def get_overall_metrics(self):
        """Return performance metrics for each group

        Returns
        -------
        pandas.Series
            The overall performance metrics
        """
        # retrive overall metrics for one of the sensitive features only as they are the same
        threshold_results = pd.DataFrame()
        if self.threshold_metrics:
            threshold_results = (
                pd.concat([self.metric_frames["thresh"].overall], axis=0)
                .rename(index="value")
                .to_frame()
            )
            threshold_results = threshold_results.reset_index().rename(
                {"index": "threshold_metric"}, axis=1
            )
            threshold_results.name = "thresholded_metric_performance"

        scalar_metrics = []
        scalar_series = pd.Series()

        if self.performance_metrics:
            scalar_metrics.append(self.metric_frames["pred"].overall)
        if self.prob_metrics:
            scalar_metrics.append(self.metric_frames["prob"].overall)

        if scalar_metrics:
            scalar_series = (
                pd.concat(scalar_metrics, axis=0).rename(index="value").to_frame()
            )
            scalar_series = scalar_series.reset_index().rename(
                {"index": "type"}, axis=1
            )

        if scalar_series.empty and threshold_results.empty:
            global_logger.warn("No overall metrics could be calculated.")
        return scalar_series, threshold_results

    @staticmethod
    def _process_metrics(metrics):
        """Separates metrics

        Parameters
        ----------
        metrics : Union[List[Metric, str]]
            list of metrics to use. These can be Metric objects
            (see credoai.modules.metrics.py), or strings.
            If strings, they will be converted to Metric objects
            as appropriate, using find_metrics()

        Returns
        -------
        Separate dictionaries and lists of metrics
        """
        # separate metrics
        failed_metrics = []
        performance_metrics = {}
        prob_metrics = {}
        threshold_metrics = {}
        for metric in metrics:
            if isinstance(metric, str):
                metric_name = metric
                metric = find_metrics(metric, MODEL_METRIC_CATEGORIES)
                if len(metric) == 1:
                    metric = metric[0]
                elif len(metric) == 0:
                    raise Exception(
                        f"Returned no metrics when searching using the provided metric name <{metric_name}>. Expected to find one matching metric."
                    )
                else:
                    raise Exception(
                        f"Returned multiple metrics when searching using the provided metric name <{metric_name}>. Expected to find only one matching metric."
                    )
            else:
                metric_name = metric.name
            if not isinstance(metric, Metric):
                raise ValidationError(
                    "Specified metric is not of type credoai.metric.Metric"
                )
            if metric.metric_category == "FAIRNESS":
                global_logger.info(
                    f"fairness metric, {metric_name}, unused by PerformanceModule"
                )
                pass
            elif metric.metric_category in MODEL_METRIC_CATEGORIES:
                if metric.takes_prob:
                    if metric.metric_category in THRESHOLD_METRIC_CATEGORIES:
                        threshold_metrics[metric_name] = metric
                    else:
                        prob_metrics[metric_name] = metric
                else:
                    performance_metrics[metric_name] = metric
            else:
                global_logger.warning(
                    f"{metric_name} failed to be used by FairnessModule"
                )
                failed_metrics.append(metric_name)

        return (performance_metrics, prob_metrics, threshold_metrics, failed_metrics)

    def _validate_arguments(self):
        check_existence(self.metrics, "metrics")
        check_data_instance(self.assessment_data, TabularData)
        check_artifact_for_nulls(self.assessment_data, "Data")
