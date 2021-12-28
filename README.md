<img src="https://raw.githubusercontent.com/credo-ai/credoai_lens/develop/docs/_static/images/credo_ai-lens.png" width="250" alt="Credo AI Lens"><br>

--------------------------------------

# Lens by Credo AI - Responsible AI Assessment Framework

Lens is a comprehensive assessment framework for AI systems. 
Lens standardizes model and data assessment, and acts as a central gateway to assessments 
created in the open source community. In short, Lens connects arbitrary AI models and datasets
with Responsible AI tools throughout the ecosystem.

Lens can be run in a notebook, a CI/CD pipeline, or anywhere else you do your ML analytics.
It is extensible, and easily customized to your organizations assessments if they are not 
supported by default. 

Though it can be used alone, Lens shows its full value when connected to your organization's 
[Credo AI Platform](https://www.credo.ai/product). Credo AI is an end-to-end AI Governance
platform that supports multi-stakeholder alignment, AI assessment (via Lens) and AI risk assesssment.



## Dependencies

- Credo AI Lens supports Python 3.7+
- Sphinx (optional for local docs site)


## Installation

The latest stable release (and required dependencies) can be installed from PyPI.
Note this installation only includes dependencies needed for a small set of modules

```
pip install credoai-lens
```

To include additional dependencies needed for some modules and demos, use the 
following installation command:

```
pip install credoai-lens[extras]
```
    

## Getting Started

To get started, we suggest running the quickstart demo: `demos/quickstart.ipynb`.
For a more detailed example, see `demos/binaryclassification.ipynb`

## Documentation

To build the documentation locally, run `make html` from the `/docs` directory and the docs site will build to: `docs/_build/html/index.html`, which can be opened in the browser.

> Make sure you have [Sphinx installed](https://www.sphinx-doc.org/en/master/usage/installation.html) if you are building the docs site locally.

## Configuration

To connect to [Credo AI's Governance Platform](https://www.credo.ai/product), enter your connection info in `~/.credoconfig` (in the root directory) using
the below format. 

```
TENANT={tenant name} # Example: credoai
CREDO_URL=<your credo url>  # Example: https://api.credo.ai 
API_KEY=<your api key> # Example: JSMmd26...
```
 
