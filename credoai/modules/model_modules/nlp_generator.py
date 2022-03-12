"""Requires installation of requirements-extras.txt"""

import pandas as pd
import os
import seaborn as sns

from absl import logging
from ._nlp_constants import PROMPTS_PATHS, PERSPECTIVE_API_MODELS
from credoai.data.utils import get_data_path
from credoai.modules.credo_module import CredoModule
from credoai.utils.common import NotRunError, ValidationError, wrap_list
from functools import partial
from googleapiclient import discovery
from time import sleep


class NLPGeneratorAnalyzer(CredoModule):
    """
    This module assesses language generation models based on various prompts and assessment attributes

    Parameters
    ----------
    prompts : str
        choices are builtin datasets, which include:
            'bold_gender', 'bold_political_ideology', 'bold_profession', 
            'bold_race', 'bold_religious_ideology' (Dhamala et al. 2021)
            'realtoxicityprompts_1000', 'realtoxicityprompts_challenging_20', 
            'realtoxicityprompts_challenging_100', 'realtoxicityprompts_challenging' (Gehman et al. 2020)
        or path of your own prompts csv file with columns 'group', 'subgroup', 'prompt'

    generation_functions : dict
        keys are names of the models and values are their callable generation functions

    assessment_functions : dict
        keys are names of the assessment functions and values could be custom callable assessment functions 
        or name of builtin assessment functions. 
        Current choices, all using Perspective API include:
                'perspective_toxicity', 'perspective_severe_toxicity', 
                'perspective_identify_attack', 'perspective_insult', 
                'perspective_profanity', 'perspective_threat'

    perspective_config : dict
        if Perspective API is to be used, this must be passed with the following:
            'api_key': your Perspective API key
            'rpm_limit': request per minute limit of your Perspective API account
    """

    def __init__(
        self,
        prompts,
        generation_functions,
        assessment_functions,
        perspective_config=None,
    ):
        super().__init__()
        self.prompts = prompts
        self.generation_functions = generation_functions
        self.assessment_functions = assessment_functions
        self.perspective_config = perspective_config
        self.perspective_client = None

    def prepare_results(self):
        """Generates summary statistics of raw assessment results generated by self.run

        Returns
        -------
        pandas.dataframe
            Summary statistics of assessment results
            Schema: ['generation_model' 'assessment_attribute', 'group', 'mean', 'std']

        Raises
        ------
        NotRunError
            Occurs if self.run is not called yet to generate the raw assessment results
        """
        if self.results is not None:
            # Calculate statistics across groups and assessment attributes
            results = (
                self.results['assessment_results'][
                    ["generation_model", "group", "assessment_attribute", "value"]
                ]
                .groupby(
                    ["generation_model", "group", "assessment_attribute"],
                    as_index=False,
                )
                .agg(mean=("value", "mean"), std=("value", "std"))
            )
            results.sort_values(
                by=["generation_model", "assessment_attribute", "group"], inplace=True
            )
            results = results[
                ["generation_model", "assessment_attribute", "group", "mean", "std"]
            ]
            return results
        else:
            raise NotRunError(
                "Results not created yet. Call 'run' with appropriate arguments before preparing results"
            )

    def run(self, n_iterations=1):
        """Run the generations and assessments

        Parameters
        ----------
        n_iterations : int, optional
            Number of times to generate responses for a prompt, by default 1
            Increase if your generation model is stochastic for a higher confidence

        Returns
        -------
        self
        """
        df = self._get_prompts(self.prompts)
        logging.info("Loaded the prompts dataset " + self.prompts)

        # Perform prerun checks
        self._perform_prerun_checks()
        logging.info(
            "Performed prerun checks of generation and assessment functions"
        )

        # Generate and record responses for the prompts with all the generation models n_iterations times
        dfruns_lst = []
        for gen_name, gen_fun in self.generation_functions.items():
            gen_fun = partial(gen_fun, num_sequences=n_iterations)
            logging.info(f"Generating {n_iterations} text responses per prompt with model: {gen_name}")
            prompts = df['prompt']
            responses = [self._gen_fun_robust(p, gen_fun) for p in prompts]   
            temp = pd.concat([df, pd.DataFrame(responses)], axis=1) \
                    .assign(prompt=prompts) \
                    .melt(id_vars=df.columns, var_name='run', value_name='response') \
                    .assign(generation_model = gen_name)

            dfruns_lst.append(temp)

        dfruns = pd.concat(dfruns_lst)

        # Assess the responses for the input assessment attributes
        logging.info("Performing assessment of the generated responses")

        dfrunst = dfruns[
            dfruns["response"] != "nlp generator error"
        ].copy()  # exclude cases where generator failed to generate a response

        dfrunst_assess_lst = []
        for assessment_attribute, assessment_fun in self.assessment_functions.items():
            logging.info(f"Performing {assessment_attribute} assessment")
            temp = dfrunst.copy()
            temp["assessment_attribute"] = assessment_attribute
            if assessment_fun in list(PERSPECTIVE_API_MODELS):
                temp["value"] = temp["response"].apply(
                    lambda x: self._assess_with_perspective(
                        x, PERSPECTIVE_API_MODELS[assessment_fun]
                    )
                )
            else:
                temp["value"] = temp["response"].apply(assessment_fun)

            dfrunst_assess_lst.append(temp)

        dfrunst_assess = pd.concat(dfrunst_assess_lst).reset_index(drop=True)

        self.results = {'assessment_results': dfrunst_assess}

        return self

    def get_results(self):
        if self.results is not None:
            return self.results
        else:
            raise NotRunError(
                "Results not created yet. Call 'run' with appropriate arguments before preparing results"
            )

    def _assess_with_perspective(self, txt, assessment_attribute):
        """Assess a text for a given assessment attribute

        Parameters
        ----------
        txt : str
            Text to be assessed
        assessment_attribute : str
            Attribute to be do the assessment based on

        Returns
        -------
        float
            assessment score
        """
        if self.perspective_client is None:
            self._build_perspective_client()

        pause_duration = 60.0 / self.perspective_config["rpm_limit"]
        sleep(pause_duration)
        analyze_request = {
            "comment": {"text": txt},
            "requestedAttributes": {assessment_attribute: {}},
            "languages": ["en"],
        }
        response = (
            self.perspective_client.comments().analyze(body=analyze_request).execute()
        )
        return response["attributeScores"][assessment_attribute]["summaryScore"][
            "value"
        ]

    def _build_perspective_client(self):
        """Build the self Perspective API client"""
        if self.perspective_client is None:
            self.perspective_client = discovery.build(
                "commentanalyzer",
                "v1alpha1",
                developerKey=self.perspective_config["api_key"],
                discoveryServiceUrl="https://commentanalyzer.googleapis.com/$discovery/rest?version=v1alpha1",
                cache_discovery=False,
            )

    def _gen_fun_robust(self, prompt, gen_fun):
        """Makes process robust to when generation_fun fails for a prompt
        Failed cases are tracked and excluded from the assessment

        Parameters
        ----------
        prompt : str
            prompt text

        Returns
        -------
        str
            response text
        """
        responses = gen_fun(prompt)
        # replace empty responses
        error_text = "nlp generator error"
        responses = [(r or error_text) if isinstance(r, str) and len(r) > 1 else error_text
                    for r in responses]
        return responses

    def _get_prompts(self, prompts):
        """Load the prompts dataset from a csv file as a dataframe

        Parameters
        ----------
        prompts : str
            One of the following:
                Name of a builtin prompt dataset. Choices are
                    'bold_gender', 'bold_political_ideology', 'bold_profession', 'bold_race', 'bold_religious_ideology' (from Dhamala et al. 2021)
                    'realtoxicityprompts_1000', 'realtoxicityprompts_challenging_20', 'realtoxicityprompts_challenging_100', 'realtoxicityprompts_challenging' (from Gehman et al. 2020)
                Path of your own prompts csv file with columns 'group', 'subgroup', 'prompt'

        Returns
        -------
        pandas.dataframe
            prompts dataframe with columns
            Schema: ['group', 'subgroup', 'prompt']

        Raises
        ------
        ValidationError
            Occurs if the provided prompts dataset csv file is not a valid file
        Exception
            Occurs if the prompts dataset cannot be loaded
        """
        if prompts in PROMPTS_PATHS:
            prompts_path = get_data_path(PROMPTS_PATHS[prompts])
            df = pd.read_csv(prompts_path)

        elif prompts.split(".")[-1] == "csv":
            df = pd.read_csv(prompts)
            cols_required = ["group", "subgroup", "prompt"]
            cols_given = list(df.columns)
            if set(cols_given) != set(cols_required):
                cols_required_str = ", ".join(cols_required)
                raise ValidationError(
                    "The provided prompts dataset csv file is not a valid file. Ensure it has all and only the following columns: "
                    + cols_required_str
                )

        else:
            builtin_prompts_names = list(PROMPTS_PATHS.keys())
            builtin_prompts_names = ", ".join(builtin_prompts_names)
            raise Exception(
                "The prompts dataset cannot be loaded. Ensure the provided prompts value is either a path to a valid csv file"
                + " or name of one of the builtin datasets (i.e."
                + builtin_prompts_names
                + "). You provided "
                + prompts
            )

        return df.reset_index(drop=True)

    def _perform_prerun_checks(self):
        """Checks the provided configurations and the generation and assessment functions

        Raises
        ------
        ValidationError
            Occurs if checks are not successfully completed
        """
        # Check types
        for item in [self.generation_functions, self.assessment_functions]:
            if not isinstance(item, dict):
                raise ValidationError(
                    "'generation_functions' and 'assessment_functions' values must be of type dict."
                )

        # Check the generation functions
        test_prompt = "To be, or not to be, that is"
        for gen_name, gen_fun in self.generation_functions.items():
            try:
                response = gen_fun(test_prompt, num_sequences=1)[0]
                if not isinstance(response, str):
                    raise ValidationError(
                        gen_name
                        + " failed to generate a string response for the test prompt '"
                        + test_prompt
                        + "'"
                    )
            except:
                raise ValidationError(
                    gen_name
                    + " failed to generate a response for the test prompt '"
                    + test_prompt
                    + "'"
                )

        # Check the assessment functions
        test_response = "The slings and arrows of outrageous fortune"
        for assessment_attribute, assessment_fun in self.assessment_functions.items():
            if assessment_fun in list(PERSPECTIVE_API_MODELS):
                if self.perspective_config is None:
                    raise ValidationError(
                        "Requested using '"
                        + assessment_fun
                        + "' but 'perspective_config' has not been provided to NLPGeneratorAnalyzer"
                    )
                for k in ["api_key", "rpm_limit"]:
                    if k not in self.perspective_config:
                        raise ValidationError(
                            "The provided 'perspective_config' is missing '" + k + "'"
                        )
                try:
                    self._assess_with_perspective(
                        test_response, PERSPECTIVE_API_MODELS[assessment_fun]
                    )
                except:
                    raise ValidationError(
                        "Perspective API function '"
                        + assessment_attribute
                        + "' failed to return a score for the test text '"
                        + test_response
                        + "'"
                    )
            else:
                try:
                    assessment_fun(test_response)
                except:
                    raise ValidationError(
                        "Assessment function '"
                        + assessment_attribute
                        + "' failed to return a score for the test text '"
                        + test_response
                        + "'"
                    )
