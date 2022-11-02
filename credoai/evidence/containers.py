"""
Generic containers for evaluator results

The containers accept raw data from the evaluators and convert it into
suitable evidences.
"""
from abc import ABC, abstractmethod

import pandas as pd
from credoai.utils import ValidationError

from deepchecks.core import SuiteResult

from .evidence import (
    MetricEvidence,
    ModelProfilerEvidence,
    ProfilerEvidence,
    TableEvidence,
    DeepchecksEvidence,
)


class EvidenceContainer(ABC):
    def __init__(self, evidence_class, data, labels=None, metadata=None):
        """Abstract Class defining Evidence Containers

        Evidence Containers are light wrappers around dataframes that
        validate their format for the purpose of evidence export. They
        define a "to_evidence" function which transforms the
        dataframe into a particular evidence format

        Parameters
        ----------
        evidence_class : Evidence
            An Evidence class
        data : pd.DataFrame
            The dataframe, formatted appropriately for the evidence type
        labels : dict
            Additional labels to pass to underlying evidence
        metadata : dict
            Metadata to pass to underlying evidence
        """
        self.evidence_class = evidence_class
        self._validate_inputs(data)
        self._validate(data)
        self._data = data
        self.labels = labels
        self.metadata = metadata or {}

    @property
    def df(self):
        return self._data

    @abstractmethod
    def to_evidence(self):
        pass

    def _validate_inputs(self, data):
        if not isinstance(data, pd.DataFrame):
            raise ValidationError("'data' must be a dataframe")

    @abstractmethod
    def _validate(self, df):
        pass


class MetricContainer(EvidenceContainer):
    """Containers for all Metric type evidence"""

    def __init__(self, df: pd.DataFrame, labels: dict = None, metadata: dict = None):
        super().__init__(MetricEvidence, df, labels, metadata)

    def to_evidence(self, **metadata):
        evidence = []
        for _, data in self._data.iterrows():
            evidence.append(
                self.evidence_class(
                    additional_labels=self.labels, **data, **self.metadata, **metadata
                )
            )
        return evidence

    def _validate(self, df):
        required_columns = {"type", "value"}
        column_overlap = df.columns.intersection(required_columns)
        if len(column_overlap) != len(required_columns):
            raise ValidationError(f"Must have columns: {required_columns}")


class TableContainer(EvidenceContainer):
    """Container for all Table type evidence"""

    def __init__(self, df: pd.DataFrame, labels: dict = None, metadata: dict = None):
        super().__init__(TableEvidence, df, labels, metadata)

    def to_evidence(self, **metadata):
        return [
            self.evidence_class(
                self._data.name, self._data, self.labels, **self.metadata, **metadata
            )
        ]

    def _validate(self, df):
        try:
            df.name
        except AttributeError:
            raise ValidationError("DataFrame must have a 'name' attribute")


class ProfilerContainer(EvidenceContainer):
    """Container for al profiler type evidence"""

    def __init__(self, df, labels: dict = None, metadata: dict = None):
        super().__init__(ProfilerEvidence, df, labels)

    def to_evidence(self, **metadata):
        return [
            self.evidence_class(self._data, self.labels, **self.metadata, **metadata)
        ]

    def _validate(self, df):
        if list(df.columns) != ["results"]:
            raise ValidationError("Profiler data must only have one column: 'results'")


class ModelProfilerContainer(EvidenceContainer):
    """Container for Model Profiler type evidence"""

    def __init__(self, df, labels=None, metadata=None):
        super().__init__(ModelProfilerEvidence, df, labels, metadata)

    def to_evidence(self, **metadata):
        return [
            self.evidence_class(self._data, self.labels, **self.metadata, **metadata)
        ]

    def _validate(self, df):
        necessary_index = ["parameters", "feature_names", "model_name"]
        if list(df.columns) != ["results"]:
            raise ValidationError(
                "Model profiler data must only have one column: 'results'"
            )
        if sum(df.index.isin(necessary_index)) != 3:
            raise ValidationError(f"Model profiler data must contain {necessary_index}")


class DeepchecksContainer(EvidenceContainer):
    """Container for all Table type evidence"""

    def __init__(
        self, name: str, data: SuiteResult, labels: dict = None, metadata: dict = None
    ):
        super().__init__(DeepchecksEvidence, data, labels, metadata)
        self.name = name

    def to_evidence(self, **metadata):
        checks_2_df = {"Check_Name": list(), "Status": list()}
        for check in self._data.get_not_passed_checks():
            checks_2_df["Check_Name"].append(check.header)
            checks_2_df["Status"].append("Not Passed")
        for check in self._data.get_passed_checks():
            checks_2_df["Check_Name"].append(check.header)
            checks_2_df["Status"].append("Passed")
        for check in self._data.get_not_ran_checks():
            checks_2_df["Check_Name"].append(check.header)
            checks_2_df["Status"].append("Not Run")

        check_results_df = pd.DataFrame.from_dict(checks_2_df, orient="columns")
        check_results_df.name = "Lens_Deepchecks_SuiteResult"
        return [
            TableEvidence(
                self.name, check_results_df, self.labels, **self.metadata, **metadata
            )
        ]

    def _validate_inputs(self, data):
        if not isinstance(data, SuiteResult):
            raise ValidationError("'data' must be a deepchecks.core.SuiteResult object")

    def _validate(self, df):
        pass
