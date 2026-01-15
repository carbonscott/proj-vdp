"""
VDP Shared Utilities.

Common functions used across VDP scripts.
"""

from config import get_tiled_url, get_api_key


def check_server():
    """Check if Tiled server is running.

    Returns:
        bool: True if server responds, False otherwise.
    """
    import urllib.request
    import urllib.error

    url = get_tiled_url()
    api_key = get_api_key()

    try:
        req = urllib.request.Request(
            f"{url}/api/v1/",
            headers={"Authorization": f"Apikey {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False


def make_artifact_key(art_row, prefix=""):
    """Generate key for artifact.

    Args:
        art_row: DataFrame row with artifact info (type, axis, Hmax_T, Ei_meV).
        prefix: Optional prefix (e.g., "path_" for metadata keys).

    Returns:
        str: Key like "mh_powder_30T" or "path_mh_powder_30T".

    Examples:
        >>> make_artifact_key(row)  # Returns "mh_powder_30T"
        >>> make_artifact_key(row, prefix="path_")  # Returns "path_mh_powder_30T"
    """
    artifact_type = art_row["type"]

    if artifact_type == "gs_state":
        key = "gs_state"
    elif artifact_type == "mh_curve":
        axis = art_row["axis"]
        hmax = int(art_row["Hmax_T"])
        key = f"mh_{axis}_{hmax}T"
    elif artifact_type == "ins_powder":
        ei = int(art_row["Ei_meV"])
        key = f"ins_{ei}meV"
    else:
        raise ValueError(f"Unknown artifact type: {artifact_type}")

    return f"{prefix}{key}" if prefix else key
