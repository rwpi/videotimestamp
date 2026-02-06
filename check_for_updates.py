# update_checker.py

import requests

def check_for_updates():
    current_version = "2.0.0-Beta4"
    repo_owner = "rwpi"
    repo_name = "videotimestamp"

    try:
        response = requests.get(f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest")
        response.raise_for_status() 
        data = response.json()

        if data.get("tag_name") and data["tag_name"] > f"VTS-{current_version}":
            return (f'Update available! Current version: {current_version}', "color: red; font-size: 10px;")
        else:
            return (f"Ver. {current_version}", "color: grey; font-size: 10px;")
    except requests.exceptions.RequestException:
        print("Failed to check for updates")
        return (f"Ver. {current_version}", "color: grey; font-size: 10px;")
