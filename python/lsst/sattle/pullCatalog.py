# This file is part of sattle.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import logging
from typing import Any
import os
import requests
import datetime


class SatCatFetcher:
    """Fetches satellite catalogs from space-track.org.

    This class provides functionality to retrieve satellite catalogs, including
    GP (General Perturbations) data and optional folder-specific data.

    Parameters
    ----------
        eltype: 'str'
         Type of elements to fetch ('elset' or other).
    Returns
    -------
        omm_dict: 'dict'
            Dictionary containing satellite catalog data.
        self._last_satf_data: 'str'
            String containing the last downloaded file.
    _______
    """
    BASE_URL = "https://www.space-track.org"
    FOLDERS = {"elset": 22700, "satf": 59}

    def __init__(self, eltype: str = "gp", use_folder: bool = False, **kwargs: Any):
        self._username = os.getenv('SPACETRACK_USER')
        self._password = os.getenv('SPACETRACK_PASSWORD')

        if self._username is None or self._password is None:
            raise ValueError(
                "Environment variables SPACETRACK_USER and SPACETRACK_PASSWORD must be set")

        self.use_folder = use_folder
        if self.use_folder:
            self._folder_id = self.FOLDERS[eltype]
        else:
            self._folder_id = None
        self._last_satf_id = -1
        self._last_satf_data = ""
        self._logger = logging.getLogger(str(__class__))

    def fetch_catalogs(self, source="gp", epoch="%3Enow-30") -> tuple[
        list[dict[str, Any]], str]:
        self._logger.info("Logging in")
        omm_list = []

        login_url = f"{self.BASE_URL}/ajaxauth/login"
        login_data = {"identity": self._username, "password": self._password}
        login_resp = requests.post(login_url, data=login_data)
        login_resp.raise_for_status()
        jar = login_resp.cookies
        self._logger.info("Successfully logged in")

        if not self.use_folder:
            gp_url = "/".join([
                self.BASE_URL,
                "basicspacedata",
                "query",
                "class", source,
                "decay_date", "null-val",
                "epoch", epoch,
                "orderby", "norad_cat_id",
                "format", "json",
            ])
            self._logger.info("Requesting GP catalog")
            gp_resp = requests.get(gp_url, cookies=jar)
            gp_resp.raise_for_status()
            omm_list = gp_resp.json()
            self._logger.info("Received GP catalog")

        if self.use_folder:
            folder_url = "/".join([
                self.BASE_URL,
                "fileshare",
                "query",
                "class", "file",
                "file_id",
                "folder_id", str(self._folder_id),
                "orderby", "file_uploaded%20desc",
                "format", "json",
                "emptyresult", "show",
            ])
            self._logger.info(
                f"Requesting file id from folder {self._folder_id}")
            folder_resp = requests.get(folder_url, cookies=jar)
            folder_resp.raise_for_status()
            folder_list = folder_resp.json()
            print(folder_resp.json())
            self._logger.info("List of folders received:" +
                              str(folder_list) + str(type(folder_list)) +
                              f" for folder id {self._folder_id}")
            self._logger.info(folder_list[0])
            self._logger.info(folder_resp)
            for folder in folder_list:
                upload_time = datetime.datetime.strptime(
                    folder['FILE_UPLOADED'],
                    '%Y-%m-%d %H:%M:%S'
                ).replace(tzinfo=datetime.timezone.utc)
                self._logger.info(f"File uploaded at {upload_time}")

            # Get the satf_id and process the file
            if len(folder_list) == 1:
                satf_id = int(folder_list[0]["FILE_ID"])
                self._logger.info(f"Received file id {satf_id}")

                if satf_id != self._last_satf_id:
                    satf_url = "/".join([
                        self.BASE_URL,
                        "fileshare",
                        "query",
                        "class", "download",
                        "file_id", str(satf_id),
                    ])
                    self._logger.info("Requesting file")
                    satf_resp = requests.get(satf_url, cookies=jar)
                    satf_resp.raise_for_status()
                    self._last_satf_data = satf_resp.text
                    self._last_satf_id = satf_id
                    self._logger.info("Received file")

                    # Parse the TLE file content into list format
                    lines = self._last_satf_data.splitlines()
                    i = 0
                    while i < len(lines):
                        line1 = lines[i].strip()
                        line2 = lines[i + 1].strip() if i + 1 < len(
                            lines) else ""

                        if line1.startswith('1 ') and line2.startswith('2 '):
                            # Create a dictionary entry for each TLE pair
                            omm_list.append({
                                'TLE_LINE1': line1,
                                'TLE_LINE2': line2
                            })
                            i += 2  # Skip to next pair
                        else:
                            i += 1  # Skip invalid lines
                    if omm_list:
                        print(omm_list[0])
            else:
                raise RuntimeError(
                    f"Unexpected number of files to download: {len(folder_list)}")

            self._logger.info(
                f"Received {len(omm_list)} satellite TLEs from CUI")

        logout_url = f"{self.BASE_URL}/ajaxauth/logout"
        self._logger.info("Logging out")
        requests.get(logout_url, cookies=jar)
        self._logger.info("Logged out")

        return omm_list, self._last_satf_data