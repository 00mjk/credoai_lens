from collections import ChainMap
from datetime import datetime
from json_api_doc import serialize
from credoai.utils.common import (NumpyEncoder, wrap_list, 
                                  ValidationError, dict_hash)
from credoai.utils.credo_api_utils import patch_metrics, post_figure

import base64
import credoai
import json
import io 
import matplotlib
import numpy as np
import pandas as pd
import pprint

META = {
  'source': 'credoai_ml_library',
  'version': credoai.__version__
}

    
class Record:
    def __init__(self, json_header, **metadata):
        self.json_header = json_header
        self.metadata = metadata
        self.creation_time = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        
    def _struct(self):
        pass
    
    def credoify(self):
        return json.dumps(serialize(data=self._struct()), cls=NumpyEncoder)
    
    def jsonify(self, filename=None):
        data = self._struct()
        if '$type' in data:
            del data['$type']
        return json.dumps({self.json_header: data}, cls=NumpyEncoder)
    
    def __str__(self):
        return pprint.pformat(self._struct())
    
class Metric(Record):
    """
    A metric record

    Records a metric value. Added to a metric table for the relevant
    control.

    Parameters
    ----------
    metric_type : string
        short identifier for metric. credoai.utils.list_metrics provides
        a list of standard metric families.
    value : float
        metric value
    dataset_variant : string, optional
        id of dataset variant on CredoAI Platform 
    metadata : dict, optional
        Arbitrary keyword arguments to append to metric as metadata

    Example
    ---------
    metric = Metric('precision_score', 0.5)
    """
    def __init__(self,
            metric_type,
            value,
            dataset_variant = None,
            **metadata):
        super().__init__('metrics', **metadata)
        self.metric_type = metric_type
        self.value = value
        self.dataset_variant = dataset_variant
        self.config_hash = dict_hash({k:v for k,v in self.__dict__.items() 
                                      if k!='value'})
    
    def _struct(self):
        return {
            'type': self.metric_type,
            'value': self.value,
            'dataset_variant_id': self.dataset_variant,
            'metadata': {'creation_time': self.creation_time,
                        **self.metadata},
            '$type': 'model_metrics'
        }
    
class Figure(Record):
    """
    A figure record

    Records a figure (either an image or a matplotlib figure).
    Attached as a figure to the associated control

    Parameters
    ----------
    name : string
        title of figure
    figure: str OR matplotlib figure
        path to image file OR matplotlib figure
    description: str, optional
        longer string describing the figure
    metadata : dict, optional
        Appended keyword arguments to append to metric as metadata

    Example
    ---------
    f = plt.figure()
    figure = Figure('Figure 1', fig=f, description='A matplotlib figure')
    """
    def __init__(self, name, figure, description=None, **metadata):
        super().__init__('figures', **metadata)
        self.name = name
        self.description = description
        self.figure_string = None
        if type(figure) == matplotlib.figure.Figure:
            self._encode_matplotlib_figure(figure)
        else:
            self._encode_figure(figure)
            

    def _encode_figure(self, figure_file):
        with open(figure_file, "rb") as figure2string:
            self.figure_string = base64.b64encode(figure2string.read()).decode('ascii')
            
    def _encode_matplotlib_figure(self, fig):
        pic_IObytes = io.BytesIO()
        fig.savefig(pic_IObytes,  format='png')
        pic_IObytes.seek(0)
        self.figure_string = base64.b64encode(pic_IObytes.read()).decode('ascii')
        
    def _struct(self):
        return {'name': self.name,
                'description': self.description,
                'file': self.figure_string,
                'creation_time': self.creation_time,
                'metadata': {'type': 'chart', **self.metadata},
                '$type': 'model_assets'}
    
class MultiRecord(Record):
    """
    A Multi-record object

    Stores multiple records of the same type

    Example
    ---------
    metric = Metric('recall', 0.6)
    model_record = MutliRecord(metric)
    """
    
    def __init__(self, records):
        self.records = wrap_list(records)
        if len(set(type(r) for r in self.records)) != 1:
            raise ValidationError
        super().__init__(self.records[0].json_header)
    
    def _struct(self):
        data = [m._struct() for m in self.records] 
        return data
    

def record_metric(metric_type, value, dataset_variant=None, **metadata):
    """Convenience function to create a metric json object

    Parameters
    ----------
    metric_type : string
        short identifier for metric. credoai.utils.list_metrics provides
        a list of standard metric families.
    value : float
        metric value
    dataset_variant : string, optional
        id of dataset variant on CredoAI Platform 
    metadata : dict, optional
        Arbitrary keyword arguments to append to metric as metadata

    Returns
    -------
    Metric object
    """    

    return Metric(metric_type, 
                  value, 
                  dataset_variant,  **metadata)

def record_metrics(metric_df):
    """
    Function to create a list of metric json objects
    
    Metrics must be properly formatted in a pandas dataframe
    
    Parameters
    ------------
    metric_df : pd.DataFrame
        dataframe where the index is the metric name and the columns
        are passed to record_metric
    metadata : dict, optional
        Arbitrary keyword arguments to append to metric as metadata
    """
    records = []
    for metric, row in metric_df.iterrows():
        records.append(record_metric(metric_type=metric, **row))
    return MultiRecord(records)

def record_metrics_from_dict(metrics, dataset_variant=None, **metadata):
    """
    Function to create a list of metric json objects from dictionary
    
    All metrics will have the same metadata (including
    dataset_variant) using this function. To assign unique metadata
    to each metric use `credoai.integration.record_metrics`
    
    Parameters
    ------------
    metrics : dict
        dictionary of metric_type : value pairs
    dataset_variant : string
        id of dataset variant on CredoAI Platform 
    metadata : dict, optional
        Arbitrary keyword arguments to append to metric as metadata
    """
    metric_df = pd.Series(metrics, name='value').to_frame()
    metadata.update({'model_label': model_label, 'dataset_variant': dataset_variant})
    metric_df = metric_df.assign(**metadata)
    return record_metrics(metric_df)
    
def export_to_file(multi_record, filename):
    """Saves record as json object to filename

    Parameters
    ----------
    multi_record : credo.integration.MutliRecord
        A MutliRecord object
    filename : str
        file to write Record json object
    """    
    json_out = multi_record.jsonify()
    with open(filename, 'w') as f:
        f.write(json_out)
        
def export_to_credo(multi_record, credo_id):
    """Sends record to Credo AI's Governance Platform

    Parameters
    ----------
    multi_record : credo.integration.MutliRecord
        A MutliRecord object
    credo_id : str
        The destination id for the model or data on 
        Credo AI's Governance platform.
    """    
    patch_metrics(credo_id, multi_record)

def export_figure_to_credo(figure_record, credo_id):
    """Sends record to Credo AI's Governance Platform

    Parameters
    ----------
    figure_record : credo.integration.Figure
        A Figure record object
    credo_id : str
        The destination id for the model or data on 
        Credo AI's Governance platform.
    """    
    post_figure(credo_id, figure_record)