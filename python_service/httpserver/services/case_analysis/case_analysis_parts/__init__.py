"""CaseAnalysisService implementation, split across mixins for maintainability.

The public CaseAnalysisService class lives in ../case_analysis_service.py and
aggregates these mixins via multiple inheritance:

    CaseAnalysisService(CaseAnalysisCoreMixin, CaseAnalysisWindowsMixin,
                        CaseAnalysisPipelinesMixin)

Each mixin owns a cohesive group of methods and shares the instance state
initialised by CaseAnalysisService.__init__.
"""

from ._core import CaseAnalysisCoreMixin
from ._windows import CaseAnalysisWindowsMixin
from ._pipelines import CaseAnalysisPipelinesMixin

__all__ = [
    "CaseAnalysisCoreMixin",
    "CaseAnalysisWindowsMixin",
    "CaseAnalysisPipelinesMixin",
]
