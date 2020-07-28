# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Dict
from pandas import DataFrame, concat, to_datetime
from lib.case_line import convert_cases_to_time_series
from lib.cast import age_group, safe_datetime_parse
from lib.io import read_file
from lib.data_source import DataSource
from lib.utils import table_rename


class PhilippinesDataSource(DataSource):
    def parse_dataframes(
        self, dataframes: Dict[str, DataFrame], aux: Dict[str, DataFrame], **parse_opts
    ) -> DataFrame:

        # Rename appropriate columns
        cases = table_rename(
            dataframes[0],
            {
                "ProvRes": "match_string_province",
                "RegionRes": "match_string_region",
                "DateDied": "date_new_deceased",
                "DateSpecimen": "date_new_confirmed",
                "DateRecover": "date_new_recovered",
                "daterepconf": "_date_estimate",
                "admitted": "_hospitalized",
                "removaltype": "_prognosis",
                "Age": "age",
                "Sex": "sex",
            },
            drop=True,
        )

        # When there is recovered removal, but missing recovery date, estimate it
        nan_recovered_mask = cases.date_new_recovered.isna() & (cases["_prognosis"] == "Recovered")
        cases.loc[nan_recovered_mask, "date_new_recovered"] = cases.loc[
            nan_recovered_mask, "_date_estimate"
        ]

        # When there is deceased removal, but missing recovery date, estimate it
        nan_deceased_mask = cases.date_new_deceased.isna() & (cases["_prognosis"] == "Died")
        cases.loc[nan_deceased_mask, "date_new_deceased"] = cases.loc[
            nan_deceased_mask, "_date_estimate"
        ]

        # Hospitalized is estimated as the same date as confirmed if admitted == yes
        cases["date_new_hospitalized"] = None
        hospitalized_mask = cases["_hospitalized"].str.lower() == "yes"
        cases.loc[hospitalized_mask, "date_new_hospitalized"] = cases.loc[
            hospitalized_mask, "date_new_confirmed"
        ]

        # Create stratified age bands
        cases.age = cases.age.apply(age_group)

        # Rename the sex values
        cases.sex = cases.sex.apply(lambda x: x.lower())

        # Drop columns which we have no use for
        cases = cases[[col for col in cases.columns if not col.startswith("_")]]

        # Go from individual case records to key-grouped records in a flat table
        data = convert_cases_to_time_series(
            cases, index_columns=["match_string_province", "match_string_region"]
        )

        # Convert date to ISO format
        data.date = data.date.apply(safe_datetime_parse)
        data = data[~data.date.isna()]
        data.date = data.date.apply(lambda x: x.date().isoformat())
        data = data.fillna(0)

        # Aggregate regions and provinces separately
        l3 = data.rename(columns={"match_string_province": "match_string"})
        l2 = data.rename(columns={"match_string_region": "match_string"})
        l2.match_string = l2.match_string.apply(lambda x: x.split(": ")[-1])

        # Ensure matching by flagging whether a record must be L2 or L3
        l2["subregion2_code"] = None
        l3["subregion2_code"] = ""

        data = concat([l2, l3]).dropna(subset=["match_string"])
        data = data[data.match_string != "Repatriate"]
        data["country_code"] = "PH"

        return data
