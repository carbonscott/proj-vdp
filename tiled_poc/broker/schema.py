"""YAML contract schema validation for dataset configs."""

import os

VALID_LAYOUTS = {"per_entity", "batched", "grouped"}
VALID_PARAM_LOCATIONS = {"root_scalars", "group", "group_scalars", "manifest"}


class ValidationError(Exception):
    """Raised when a dataset YAML fails validation."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(f"{len(errors)} validation error(s):\n" + "\n".join(f"  - {e}" for e in errors))


def validate(cfg):
    """Validate a parsed dataset YAML config.

    Args:
        cfg: dict loaded from YAML.

    Returns:
        list of warning strings (non-fatal).

    Raises:
        ValidationError: if required fields are missing or invalid.
    """
    errors = []
    warnings = []

    # --- Required identity fields ---
    if not cfg.get("label"):
        errors.append("'label' is required (e.g., edrixs_sbi)")
    if not cfg.get("key_prefix"):
        errors.append("'key_prefix' is required (e.g., edrixs)")

    # --- Data section ---
    data = cfg.get("data")
    if not data:
        errors.append("'data' section is required")
    else:
        if not data.get("directory"):
            errors.append("'data.directory' is required")
        elif not os.path.isdir(data["directory"]):
            errors.append(f"'data.directory' does not exist: {data['directory']}")

        layout = data.get("layout")
        if not layout:
            errors.append("'data.layout' is required (per_entity | batched | grouped)")
        elif layout not in VALID_LAYOUTS:
            errors.append(f"'data.layout' must be one of {VALID_LAYOUTS}, got '{layout}'")

        if not data.get("file_pattern"):
            warnings.append("'data.file_pattern' not set — will default to '**/*.h5'")

    # --- Artifacts ---
    artifacts = cfg.get("artifacts", [])
    if not artifacts:
        errors.append("'artifacts' list is required (at least one artifact)")
    else:
        for i, art in enumerate(artifacts):
            if not art.get("type"):
                errors.append(f"artifacts[{i}].type is required")
            if not art.get("dataset"):
                errors.append(f"artifacts[{i}].dataset is required")

    # --- Parameters (optional but validated if present) ---
    params = cfg.get("parameters")
    if params:
        loc = params.get("location")
        if loc and loc not in VALID_PARAM_LOCATIONS:
            errors.append(f"'parameters.location' must be one of {VALID_PARAM_LOCATIONS}, got '{loc}'")
        if loc == "group" and not params.get("group"):
            errors.append("'parameters.group' is required when location is 'group'")
        if loc == "manifest" and not params.get("manifest"):
            errors.append("'parameters.manifest' is required when location is 'manifest'")

    # --- Shared axes (optional, validated if present) ---
    for i, ax in enumerate(cfg.get("shared", [])):
        if not ax.get("type"):
            errors.append(f"shared[{i}].type is required")
        if not ax.get("dataset"):
            errors.append(f"shared[{i}].dataset is required")

    if errors:
        raise ValidationError(errors)

    return warnings
