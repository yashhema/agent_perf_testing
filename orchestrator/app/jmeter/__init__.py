"""JMeter execution module.

Handles:
- JMX test plan generation
- JMX deployment to load generators
- Starting JMeter load tests
- Monitoring JMeter execution
- Collecting JMeter results
"""

from app.jmeter.service import JMeterService
from app.jmeter.models import (
    JMeterConfig,
    JMeterExecutionResult,
    JMeterStatus,
)
from app.jmeter.template import (
    JMXTemplateManager,
    JMXTestPlanConfig,
    HTTPSamplerConfig,
    create_default_test_plan,
)
from app.jmeter.deployment import (
    JMXDeploymentService,
    TestPlanSpec,
    SSHFileTransferAdapter,
)

__all__ = [
    # Service
    "JMeterService",
    "JMXDeploymentService",
    # Models
    "JMeterConfig",
    "JMeterExecutionResult",
    "JMeterStatus",
    "TestPlanSpec",
    # Template
    "JMXTemplateManager",
    "JMXTestPlanConfig",
    "HTTPSamplerConfig",
    "create_default_test_plan",
    # Adapters
    "SSHFileTransferAdapter",
]
