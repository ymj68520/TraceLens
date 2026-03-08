"""
Dynamic loader for all extractor plugins.
This module scans the current directory for python files and imports them.
Any class decorated with @register_extractor will be automatically registered locally.
"""
import os
import importlib
import logging
import json

logger = logging.getLogger(__name__)

# The global registry acting as our routing map.
# Key: string extension (e.g. ".pdf", "leveldb"), Value: initialized Extractor instance
extractor_registry = {}

# Staging ground for subclasses that use @register_extractor
registered_extractor_classes = {}

def get_extractor(extension: str):
    """Retrieves an extractor for the given extension, returning None if unsupported."""
    return extractor_registry.get(extension.lower())

def load_plugins():
    """Dynamically loads all modules, then reads JSON mapping to build instances."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    package_name = __name__

    # 1. Load all modules so decorators execute and populate `registered_extractor_classes`
    for filename in os.listdir(current_dir):
        if filename.endswith(".py") and filename != "__init__.py" and filename != "base.py":
            module_name = filename[:-3]
            try:
                importlib.import_module(f"{package_name}.{module_name}")
            except Exception as e:
                logger.error(f"Failed to load extractor plugin {module_name}: {e}")

    # 2. Read the JSON mapping config
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))), "config", "extractor_mapping.json")
    mapping = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read extractor_mapping.json: {e}")
    else:
        logger.warning(f"No extractor_mapping.json found at {config_path}. No routes will be built!")

    # 3. Build the actual registry
    # Initialize a singleton instance for each class, then map it to the extensions
    instances = {}
    for class_name, ext_list in mapping.items():
        if class_name in registered_extractor_classes:
            cls = registered_extractor_classes[class_name]
            
            # Create a singleton of the class if we haven't already
            if class_name not in instances:
                try:
                    instances[class_name] = cls()
                except Exception as e:
                    logger.error(f"Failed to instantiate {class_name}: {e}")
                    continue
            
            # Register the extensions pointing to the singleton instance
            instance = instances[class_name]
            for ext in ext_list:
                extractor_registry[ext.lower()] = instance
        else:
            logger.warning(f"Mapped class '{class_name}' not found in any loaded plugins.")

# This ensures plugins are loaded as soon as `extractors` is imported
load_plugins()
