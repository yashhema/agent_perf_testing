"""JMX Preprocessor Element Builders.

Creates preprocessor elements like JSR223 PreProcessor.
"""

import xml.etree.ElementTree as ET
from .base import create_string_prop, create_bool_prop


def create_jsr223_preprocessor(
    name: str,
    script: str,
    language: str = "groovy",
    cache_key: str = "true"
) -> ET.Element:
    """Create a JSR223 PreProcessor element.

    Args:
        name: Preprocessor name
        script: Script code to execute
        language: Scripting language (groovy, javascript, etc.)
        cache_key: Whether to cache compiled script
    """
    preprocessor = ET.Element('JSR223PreProcessor', {
        'guiclass': 'TestBeanGUI',
        'testclass': 'JSR223PreProcessor',
        'testname': name,
        'enabled': 'true'
    })

    preprocessor.append(create_string_prop('scriptLanguage', language))
    preprocessor.append(create_string_prop('parameters', ''))
    preprocessor.append(create_string_prop('filename', ''))
    preprocessor.append(create_string_prop('cacheKey', cache_key))
    preprocessor.append(create_string_prop('script', script))

    return preprocessor


def create_jsr223_postprocessor(
    name: str,
    script: str,
    language: str = "groovy",
    cache_key: str = "true"
) -> ET.Element:
    """Create a JSR223 PostProcessor element."""
    postprocessor = ET.Element('JSR223PostProcessor', {
        'guiclass': 'TestBeanGUI',
        'testclass': 'JSR223PostProcessor',
        'testname': name,
        'enabled': 'true'
    })

    postprocessor.append(create_string_prop('scriptLanguage', language))
    postprocessor.append(create_string_prop('parameters', ''))
    postprocessor.append(create_string_prop('filename', ''))
    postprocessor.append(create_string_prop('cacheKey', cache_key))
    postprocessor.append(create_string_prop('script', script))

    return postprocessor


# Pre-defined preprocessor scripts

FILE_OPERATION_SCRIPT = '''
// Determine is_confidential and make_zip based on percentages
def confPercent = Integer.parseInt(vars.get("CONFIDENTIAL_PERCENT") ?: "0")
def zipPercent = Integer.parseInt(vars.get("ZIP_PERCENT") ?: "20")

def random = new Random()
def confRoll = random.nextInt(100) + 1
def zipRoll = random.nextInt(100) + 1

vars.put("is_confidential", confRoll <= confPercent ? "true" : "false")
vars.put("make_zip", zipRoll <= zipPercent ? "true" : "false")
'''

FILE_OPERATION_NO_CONF_SCRIPT = '''
// Determine make_zip based on percentage (no confidential data)
def zipPercent = Integer.parseInt(vars.get("ZIP_PERCENT") ?: "20")

def random = new Random()
def zipRoll = random.nextInt(100) + 1

vars.put("is_confidential", "false")
vars.put("make_zip", zipRoll <= zipPercent ? "true" : "false")
'''


def create_file_operation_preprocessor(include_confidential: bool = True) -> ET.Element:
    """Create preprocessor for file operation parameter determination."""
    script = FILE_OPERATION_SCRIPT if include_confidential else FILE_OPERATION_NO_CONF_SCRIPT
    return create_jsr223_preprocessor(
        name="Determine File Parameters",
        script=script
    )
