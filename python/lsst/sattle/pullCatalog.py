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
import getpass
import logging
from typing import Any
import os
import requests

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
    FOLDERS = {"elset": 10}

    def __init__(self, eltype: str = "gp"):
        self._username = os.getenv( 'SPACETRACK_USER')
        self._password = os.getenv('SPACETRACK_PASSWORD')

        if self._username is None or self._password is None:
            raise ValueError(
                "Environment variables SPACETRACK_USER and SPACETRACK_PASSWORD must be set")

        self.use_folder = False
        if eltype not in self.FOLDERS:
            self._folder_id = None
            self.use_folder = False
        else:
            self._folder_id = self.FOLDERS[eltype]
        self._last_satf_id = -1
        self._last_satf_data = ""
        self._logger = logging.getLogger(str(__class__))

    def fetch_catalogs(self, source="gp", epoch="%3Enow-30") -> tuple[dict[str, Any], str]:
        self._logger.info("Logging in")

        login_url = f"{self.BASE_URL}/ajaxauth/login"
        login_data = {"identity": self._username, "password": self._password}
        login_resp = requests.post(login_url, data=login_data)
        login_resp.raise_for_status()
        jar = login_resp.cookies
        self._logger.info("Successfully logged in")

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
        omm_dict = gp_resp.json()
        self._logger.info("Received GP catalog")

        if self.use_folder:

            folder_url = "/".join([
                self.BASE_URL,
                "fileshare",
                "query",
                "class", "file",
                "predicates", "file_id",
                "folder_id", str(self._folder_id),
                "orderby", "file_uploaded%20desc",
                "limit", "1",
                "format", "json",
                "emptyresult", "show",
            ])
            self._logger.info(f"Requesting file id from folder {self._folder_id}")
            folder_resp = requests.get(folder_url, cookies=jar)
            folder_resp.raise_for_status()
            folder_list = folder_resp.json()
            if len(folder_list) == 1:
                satf_id = int(folder_list[0]["FILE_ID"])
            else:
                raise RuntimeError(f"Unexpected number of files to download: {len(folder_list)}")
            self._logger.info(f"Received file id {satf_id}")

            if satf_id != self._last_satf_id:
                satf_url = "/".join([
                    self.BASE_URL,
                    "fileshare",
                    "query",
                    "class", "download",
                    "file_id", str(satf_id),
                ])
                self._logger.info(f"Requesting file")
                satf_resp = requests.get(satf_url, cookies=jar)
                satf_resp.raise_for_status()
                self._last_satf_data = satf_resp.text
                self._last_satf_id = satf_id
                self._logger.info(f"Received file")

        logout_url = f"{self.BASE_URL}/ajaxauth/logout"
        # Ignore result
        self._logger.info(f"Logging out")
        requests.get(logout_url, cookies=jar)
        self._logger.info(f"Logged out")

        #TODO: If dictionary is empty, we need to stop and send an error/warning??

        return omm_dict, self._last_satf_data