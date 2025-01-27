
# Intro:
This script is designed to clean and transform data exported from MindLogger. It processes the export files provided as input and generates multiple output files, as detailed in the sections below

# Who can use this:
Administrators seeking to further refine or clean data from export files


# Output Files:
This documentation will discuss the output files that are written out in our example script. 
List of output files:
report_all.csv
applet_data_dict.csv
report_response_formatted.csv
report_response_formatted_widened.csv
response_wide_split_by_activity.zip


1. report_all.csv
For large applets with extensive data collection, data exports are split into multiple report_response CSV files. This file is the final result after combining all report_response files into one large file. The data is exactly the same as the original files, and you can find more information about what each column means in the Help Center

2. applet_data_dict.csv
This file contains applet configuration details. It has applet info like  activity names, flow names, items, prompts and options per each applet version. MindLogger allows applets to be updated during data collection. This means the data collected for each version would be different. For further details, you can visit the Help Center.

3. report_response_formatted.csv
MindLogger collects many types of data, and the responses can vary. This file processes the data to make it more uniform and easy to understand:
It standardizes the way different types of answers are shown (like geo location, time and time range).
It also converts timestamps into a readable date and time format
It contains responses and scores mapped and available as separate columns - response_value and response_score
Also, subscale scores are reorganized as rows. Subscale scores are renamed as subscale_name_[Subscale Name] and optional text as subscale_lookup_text_[Subscale Name]
Data dictionary explaining each of the columns is available in Help Center

4. report_response_formatted_widened.csv
MindLogger typically stores data in a "long format," but that can be difficult to analyze. The report_response_formatted_widened.csv file transforms the data into a "wide format," which is better for analysis. Subscale scores (like final scores) are kept separate to make the data clearer.

5. response_wide_split_by_activity.zip
This contains the data in widened format split by one file (csv) per activity




# Technical Documentation

load_and_merge_response_files()
This function imports all these files and combines them into a single data frame. The result, report_all.csv, is the consolidated file containing all the merged data. The columns in this file are identical to those found in the original report_response files. For detailed information on the column definitions, refer to the Help Center

extract_applet_data_dict()
The function outputs response_history.csv, which contains columns like version, activity_flow_id, activity_flow_name, activity_id, activity_name, item_id, item, prompt, and options. These columns match the original report_response files. For further details, consult the Help Center

subscale_transform_long_format()

This function reworks this data into a consistent long format by renaming the subscale score columns and adding them under the item column with corresponding values under the response column

format_response()
Removes prefixes and formats data types (e.g., geolocation, time items, time range items).

response_value_score_mapping()
Maps response values to scores or labels, depending on the options set in the Admin Panel.

format_epochtime()
Converts epoch UTC timestamps into human-readable date and time formats.

widen_data()
MindLogger data is converted into a wide format by this  function.

response_wide_split_by_activity()
MindLogger data is converted into a wide format and then split into different files per activity by this  function

