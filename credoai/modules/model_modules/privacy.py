import numpy as np
import pandas as pd
import copy

from art.estimators.classification.scikitlearn import SklearnClassifier
from art.attacks.inference.membership_inference import (
    MembershipInferenceBlackBoxRuleBased,
    MembershipInferenceBlackBox,
)
from credoai.modules.credo_module import CredoModule
from sklearn.model_selection import train_test_split
from sklearn import metrics as sk_metrics
import warnings

warnings.filterwarnings("ignore")


class PrivacyModule(CredoModule):
    """Privacy module for Credo AI.

    This module takes in model and data and provides functionality to perform privacy assessment

    Parameters
    ----------
    model : model
        A trained ML model
    x_train : pandas.DataFrame
        The training features
    y_train : pandas.Series
        The training outcome labels
    x_test : pandas.DataFrame
        The test features
    y_test : pandas.Series
        The test outcome labels
    """

    def __init__(
        self, model, x_train, y_train, x_test, y_test, attack_train_ratio=0.50
    ):

        self.x_train = x_train.to_numpy()
        self.y_train = y_train.to_numpy()
        self.x_test = x_test.to_numpy()
        self.y_test = y_test.to_numpy()
        self.model = model.model
        self.attack_train_ratio = attack_train_ratio
        self.attack_model = SklearnClassifier(self.model)
        np.random.seed(10)

    def run(self):
        """Runs the assessment process

        Returns
        -------
        dict
            Key: metric name
            Value: metric value
        """
        rule_based_attack_performance = self._rule_based_attack()
        model_based_attack_performance = self._model_based_attack()

        self.results = {
            **rule_based_attack_performance,
            **model_based_attack_performance,
        }

        return self

    def prepare_results(self):
        """Prepares results for export to Credo AI's Governance App

        Structures a subset of results for export as a dataframe with appropriate structure
        for exporting. See credoai.modules.credo_module.

        Returns
        -------
        pd.DataFrame

        Raises
        ------
        NotRunError
            If results have not been run, raise
        """
        if self.results is not None:
            metric_types = [
                "rule_based_attack_accuracy_score",
                "model_based_attack_accuracy_score",
            ]

            index = []
            prepared_arr = []
            for metric_type in metric_types:
                if metric_type not in self.results:
                    continue
                val = self.results[metric_type]
                if isinstance(val, list):
                    for l in val:
                        index.append(metric_type)
                        prepared_arr.append(l)
                else:
                    if isinstance(val, dict):
                        tmp = val
                    elif isinstance(val, (int, float)):
                        tmp = {"value": val}
                    index.append(metric_type)
                    prepared_arr.append(tmp)
            return pd.DataFrame(prepared_arr, index=index).rename_axis(
                index="metric_type"
            )
        else:
            raise NotRunError("Results not created yet. Call 'run' to create results")

    def _rule_based_attack(self):
        """Rule-based privacy attack

        The rule-based attack uses the simple rule to determine membership in the training data:
            if the model's prediction for a sample is correct, then it is a member.
            Otherwise, it is not a member.

        Returns
        -------
        dict
            Key: metric name
            Value: metric value
        """
        attack = MembershipInferenceBlackBoxRuleBased(self.attack_model)

        # undersample training/test so that they are balanced
        if len(self.x_test) < len(self.x_train):
            idx = np.random.choice(
                np.arange(len(self.x_train)), len(self.x_test), replace=False
            )
            inferred_train = attack.infer(self.x_train[idx], self.y_train[idx])
            inferred_test = attack.infer(self.x_test, self.y_test)
        else:
            idx = np.random.choice(
                np.arange(len(self.x_test)), len(self.x_train), replace=False
            )
            inferred_train = attack.infer(self.x_train, self.y_train)
            inferred_test = attack.infer(self.x_test[idx], self.y_test[idx])

        # check performance
        y_pred = np.concatenate([inferred_train.flatten(), inferred_test.flatten()])
        y_true = np.concatenate(
            [
                np.ones(len(inferred_train.flatten()), dtype=int),
                np.zeros(len(inferred_test.flatten()), dtype=int),
            ]
        )
        accuracy_score = sk_metrics.accuracy_score(y_true, y_pred)

        attack_performance = {"rule_based_attack_accuracy_score": accuracy_score}

        return attack_performance

    def _model_based_attack(self):
        """Model-based privacy attack

        The model-box attack trains an additional classifier (called the attack model)
            to predict the membership status of a sample. It can use as input to the learning process
            probabilities/logits or losses, depending on the type of model and provided configuration.

        Returns
        -------
        dict
            Key: metric name
            Value: metric value
        """
        attack_train_size = int(len(self.x_train) * self.attack_train_ratio)
        attack_test_size = int(len(self.x_test) * self.attack_train_ratio)

        attack = MembershipInferenceBlackBox(self.attack_model)

        # train attack model
        attack.fit(
            self.x_train[:attack_train_size],
            self.y_train[:attack_train_size],
            self.x_test[:attack_test_size],
            self.y_test[:attack_test_size],
        )

        x_train_assess, y_train_assess = (
            self.x_train[attack_train_size:],
            self.y_train[attack_train_size:],
        )
        x_test_assess, y_test_assess = (
            self.x_test[attack_test_size:],
            self.y_test[attack_test_size:],
        )
        
        # undersample training/test so that they are balanced
        if len(x_test_assess) < len(x_train_assess):
            idx = np.random.choice(
                np.arange(len(x_train_assess)), len(x_test_assess), replace=False
            )
            inferred_train = attack.infer(x_train_assess[idx], y_train_assess[idx])
            inferred_test = attack.infer(x_test_assess, y_test_assess)
        else:
            idx = np.random.choice(
                np.arange(len(x_test_assess)), len(x_train_assess), replace=False
            )
            inferred_train = attack.infer(x_train_assess, self.y_train_assess)
            inferred_test = attack.infer(x_test_assess[idx], y_test_assess[idx])

        # check performance
        y_pred = np.concatenate([inferred_train.flatten(), inferred_test.flatten()])
        y_true = np.concatenate(
            [
                np.ones(len(inferred_train.flatten()), dtype=int),
                np.zeros(len(inferred_test.flatten()), dtype=int),
            ]
        )

        accuracy_score = sk_metrics.accuracy_score(y_true, y_pred)

        attack_performance = {"model_based_attack_accuracy_score": accuracy_score}

        return attack_performance
