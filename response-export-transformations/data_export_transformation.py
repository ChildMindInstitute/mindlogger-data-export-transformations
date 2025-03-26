# %%
#Import libraries
import pandas as pd
import numpy as np
import re, os, sqlite3
from datetime import datetime
from pathlib import Path
from packaging.version import Version
import zipfile
import argparse

# %%
def load_and_merge_response_files(input_dir):
    """
    Reads and combines all CSV files starting with 'report' from the specified directory.
    """
    try:
        # Find all files starting with 'report' in the directory
        report_files = input_dir.glob('responses*.csv')
        
        # Read and combine CSV files on the fly
        combined_df = pd.concat(
            (pd.read_csv(file, encoding='UTF-8') for file in report_files),
            ignore_index=True
        )
        
        # Rename the first column
        combined_df.rename(columns={combined_df.columns[0]: 'target_id', 'activity_start_time' : 'activity_start_time_utc', 
                                    'activity_end_time' : 'activity_end_time_utc', 'activity_schedule_start_time' : 'activity_schedule_start_time_utc'}, inplace=True)
        
        return combined_df

    except FileNotFoundError:
        print(f"Error: Directory {input_dir} not found.")
    except pd.errors.EmptyDataError:
        print("Error: One or more files are empty.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    
    # Return an empty DataFrame if an error occurs
    return pd.DataFrame()

# %%

def extract_applet_data_dict(data):
    """
    Extracts applet details and saves to a seperate file as applet dictionary
    """
    return data[['applet_version', 'activity_flow_id', 'activity_flow_name', 
                 'activity_id', 'activity_name', 'item_id', 
                 'item_name', 'item_prompt', 'item_response_options']].drop_duplicates()


def subscale_transform_long_format(data):
    """
    Transforms subscale columns into rows
    """
    # Remove 'legacy_user_id' if it exists
    if 'legacy_user_id' in data.columns:
        data = data.drop(columns=['legacy_user_id', 'rawScore'])
    
    melt_df = data.drop(columns=['item_name','item_response','item_id','item_prompt','item_response_options'])

    id_vars = data[['activity_submission_id', 'activity_flow_submission_id',
        'activity_schedule_start_time_utc', 'activity_start_time_utc', 'activity_end_time_utc',
        'item_response_status', 'secret_user_id', 'userId', 'source_id',
        'source_secret_id', 'source_nickname', 'source_relation',
        'source_tag', 'target_id', 'target_secret_id',
        'target_nickname', 'target_tag', 'input_id',
        'input_secret_id', 'input_nickname', 'activity_id',
        'activity_name', 'activity_flow_id', 'activity_flow_name', 'applet_version', 
        'activity_submission_review_id', 'activity_schedule_id', 'utc_timezone_offset']].columns.to_list()

    value_vars = data.columns[data.columns.get_loc('item_response_status')+1:].tolist()
    
    if not value_vars:  # Check if the list is empty
        print(" No Subscale Scores Present")
    else:

        # Reshape the DataFrame using melt for columns after 'utc_timezone_offset'
        reshaped_data = melt_df.melt(
            id_vars= id_vars,         # Columns to keep as identifiers
            value_vars=value_vars,   # Columns to reshape
            var_name="item_name",         # New column to hold column names
            value_name="item_response"    # New column to hold corresponding values
        ).dropna(subset=['item_response'])

            # Add additional computed columns
        reshaped_data = reshaped_data.assign(
            item_id='',
            item_prompt= '',
            item_response_options='',
        )    


        # Prepare a subset of the original DataFrame for alignment
        subset_data = data[reshaped_data.columns.tolist()]

        # Combine the subset and reshaped DataFrame
        joined_data = pd.concat([subset_data, reshaped_data], axis=0, ignore_index=True)
    
        # Sort by ID, date, and the origin column
        joined_data['origin'] = ['items'] * len(subset_data) + ['scores'] * len(reshaped_data)
        joined_data.sort_values(by=['activity_start_time_utc', 'activity_submission_id', 'origin'], ascending=[False, True, True], inplace=True)
        joined_data.drop(columns=['origin'], inplace=True)
        joined_data.reset_index(drop=True, inplace=True)

        return joined_data


def format_epochtime(data, column_name):
    """
    Convert epoch time in milliseconds to datetime.
    """    
    return pd.to_datetime(pd.to_numeric(data[column_name], errors='coerce') / 1000, unit='s', errors='coerce')


# %%
def format_response(data): 
    formatted_responses = []

    for i, row in data.iterrows():
        response = row.get('item_response', None)

        # Ensure response is a string or NaN
        if not isinstance(response, str):
            response = str(response) if not pd.isna(response) else np.nan

        # Clean responses
        if isinstance(response, str):
            if "geo:" in response:
                geo_match = re.search(r'geo:\s*lat\s*\((.*?)\)\s*/\s*long\s*\((.*?)\)', response)
                if geo_match:
                    lat, long = geo_match.groups()
                    formatted_responses.append(f"{lat.strip()}/{long.strip()}")
                    continue

            if "value:" in response:
                formatted_responses.append(re.sub(r"value:\s*", "", response))
                continue

            if "date:" in response:
                formatted_responses.append(re.sub(r"date:\s*", "", response))
                continue

            if pd.isna(response):  # Handle NaN explicitly
                formatted_responses.append(np.nan)
                continue

            if "time:" in response:
                time_match = re.search(r'hr\s*(\d{1,2}),\s*min\s*(\d{1,2})', response)
                if time_match:
                    hour, minute = map(int, time_match.groups())
                    formatted_responses.append(f"{hour:02}:{minute:02}")
                    continue
                formatted_responses.append(np.nan)
                continue

            if "time_range:" in response:
                try:
                    clean_time = re.sub(r'[a-zA-Z\s+(\)_:]', '', response).replace(',', ':')
                    time_parts = clean_time.split('/')
                    formatted_parts = [
                        f"{part.split(':')[0].zfill(2)}:{part.split(':')[1].zfill(2)}"
                        for part in time_parts
                    ]
                    formatted_responses.append('/'.join(formatted_parts))
                except (IndexError, ValueError):
                    formatted_responses.append(np.nan)
                continue

        # Fallback case
        formatted_responses.append(response)

    return pd.Series(formatted_responses)

# %%
def response_value_score_mapping(data):
    
    response_scores = []
    response_values = []

    for options, response in zip(data['item_response_options'], data['item_response']):
        # Ensure 'options' and 'response' are valid strings
        if not isinstance(options, str) or not isinstance(response, str):
            response_scores.append(np.nan)
            response_values.append(np.nan)
            continue

        if " | text: " in response: 
                response = re.sub(r'\s\|\stext:.*', '', response)

        # Check if options contain scores
        if "score: " in options:
            # Parse options and responses
            split_options = [opt.strip() for opt in options.strip().split("),") if "(score" in opt]
            split_response = [resp.strip() for resp in response.strip().split(": ")[1].split(',')]

            # Build the score mapping dictionary
            scores = {
                opt.split(": ")[1].split(" ")[0]:  # Extract position part
                opt.split("score: ")[1].strip(" )")  # Extract score part
                for opt in split_options if "score: " in opt
            }
            
            score_values = {
                opt.split(": ")[1].split(" ")[0]:  # Extract position part
                opt.split(":")[0].strip()  # Extract value part
                for opt in split_options if "score: " in opt
            }

            # Map responses to scores
            response_score_mapping = [scores.get(resp, "N/A") for resp in split_response]
            response_scores.append(", ".join(response_score_mapping))

            response_score_value_mapping = [score_values.get(resp, "N/A") for resp in split_response]
            response_values.append(", ".join(response_score_value_mapping))
            
        elif  ": " in options:
            if re.search(r'^Min: [1-9]\d*, Max: ', options):
                max_value = re.sub(r'^Min: [1-9]\d*, Max: ', '', options)
                max_value = int(max_value)

                if max_value > 1: 
                    slider_response = re.sub('value: ', '', response)
                    response_values.append(", ".join(slider_response))
                    response_scores.append(np.nan)
                
            else:
                value_options = ', ' + options + ','
                split_options_text = [opt.strip() for opt in re.findall(r',\s(.*?):', value_options)]
                split_options_value = [opt.strip() for opt in re.findall(r':\s(\d+),', value_options)]
                split_response_values = [resp.strip() for resp in response.strip().split(": ")[1].split(',')]

                # Build actual response mapping
                values = {
                    value: text  # Map position (value) to response text
                    for text, value in zip(split_options_text, split_options_value)
                }
                
                # Map response positions to actual values
                response_value_mapping = [values.get(resp, re.sub('value: ', '', response)) for resp in split_response_values]
                response_values.append(", ".join(response_value_mapping))
                response_scores.append(np.nan)
        
        else:
            response_scores.append(np.nan)
            response_values.append(np.nan)

    return pd.Series(response_values), pd.Series(response_scores)


def widen_data(data, column_list):
    """
    Transforms data into a wide format based on the specified column list.
    """



    # merge formatted response, values and scores created a single response field
    data = data.copy()
    data['merged_responses'] = data['response_scores'].combine_first(data['response_values']).combine_first(data['formatted_response'])

    # Convert datetime columns to string and handle NaT
    datetime_cols = data.select_dtypes(include=['datetime']).columns
    data[datetime_cols] = data[datetime_cols].astype(str).replace('NaT', '')

    # Fill missing values in specified columns
    data[column_list] = data[column_list].fillna('')

    # Group by the column list and combine IDs
    answers = data.groupby(column_list)['activity_submission_id'].apply(lambda x: '|'.join(x.astype(str))).reset_index()

    # Create combined column names
    data['combined_cols'] = data['item_name'].astype(str)
 

    # Select relevant columns for pivoting
    subset_columns = column_list + ['combined_cols', 'merged_responses']

    #Create row order
    dat_subset = data[subset_columns].copy()  # Explicitly make a copy
    dat_subset['row_order'] = range(len(dat_subset))

    # Pivot the data into wide format
    dat_wide = pd.pivot_table(
        dat_subset, 
        index=column_list, 
        columns='combined_cols', 
        values='merged_responses', 
        aggfunc='last'
    ).reset_index()

    column_order = dat_subset.sort_values(by='row_order')['combined_cols'].unique()

    # Reorder the wide DataFrame columns based on the original row order
    reordered_columns = list(column_list) + list(column_order)
    dat_wide = dat_wide.reindex(columns=reordered_columns, fill_value='')

    # Merge with the combined IDs
    dat_wide = pd.merge(dat_wide, answers, on=column_list, how='outer')
    
    return dat_wide



def response_wide_split_by_activity(data, column_list, output_path):

    #Group data by activity_id
    report_response_by_activity = {key: group for key, group in data.groupby('activity_id')}

    # Get the latest name for each id
    activity_version = data[['applet_version', 'activity_id', 'activity_name']].drop_duplicates()
    activity_version = activity_version.dropna(subset=['applet_version'])
    activity_version['version_obj'] = activity_version['applet_version'].apply(Version)
    activity_version = activity_version.sort_values(by=['activity_id', 'version_obj'], ascending=[True, False])
    latest_versions = activity_version.groupby('activity_id').head(1).drop(columns='version_obj').reset_index(drop=True)
    latest_versions['activity_name'] = latest_versions['activity_name'].apply(lambda x: re.sub(r'[^\w\s]', '_', x))

    # Define the folder to save the CSV files
    output_zip_path = output_path / "response_wide_split_by_activity.zip"

     # Create a new zip file to store the CSV files
    with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Apply the function to each DataFrame and save as CSV inside the zip file
        for id_value, df in report_response_by_activity.items():
            # Merge the name from latest_versions based on 'activity_id'
            name_df = latest_versions[latest_versions['activity_id'] == id_value]
            if not name_df.empty:
                activity_name = name_df['activity_name'].values[0]
            else:
                activity_name = f"Unknown_{id_value}"

            # Apply the widen_data function to reshape the DataFrame
            wide_df = widen_data(df, column_list)

            # Construct the filename for the CSV to be saved inside the zip file
            csv_filename = f"wide_data_activityName[{activity_name}]_activityId[{id_value}].csv"

            # Convert DataFrame to CSV and write it directly into the zip file
            with zipf.open(csv_filename, 'w') as file:
                wide_df.to_csv(file, index=False)
                #print(f"Saved CSV for {activity_name} (id={id_value}) to {csv_filename} inside the zip archive")
    
    #print(f"All files have been saved in the zip archive: {output_zip_path}")

# %%
# Main function to coordinate execution
def main():
    parser = argparse.ArgumentParser(description="Data Export Transformation Script")
    parser.add_argument("--input_path", required=True, help="Path to the input folder containing files")
    parser.add_argument("--output_path", required=True, help="Path to the output folder to save results")
    #parser.add_argument("--tasks", nargs="+", default=["process"], 
    #                    help="Tasks to execute: process, validate, report, extract_applet, transform_subscale")
    
    args = parser.parse_args()
    input_path = Path(args.input_path)
    output_path = Path(args.output_path)
    #tasks = args.tasks

    final_column_list = [
    'userId', 'secret_user_id', 'source_secret_id', 
    'target_secret_id', 'input_secret_id', 
    'activity_start_time_utc', 'activity_end_time_utc', 'activity_schedule_start_time_utc',
    'activity_flow_id', 'activity_flow_name', 
    'activity_id', 'activity_name', 
    'activity_schedule_id', 'applet_version'
    ]

    # merges all report.csv files and creates merged output - report_all.csv
    response_data = load_and_merge_response_files(input_path)
    if not response_data.empty:
        output_file = output_path / 'report_all.csv'
        output_path.mkdir(parents=True, exist_ok=True)  # Ensure output directory exists
        response_data.to_csv(output_file, index=False)
        print("\n" + "=" * 50)
        print("report_all.csv file saved")
        print("=" * 50)
    else:
        print("\n" + "=" * 50)
        print("No data to combine or no matching files found.")
        print("=" * 50)


    # Process the response data and save applet data dictionary to CSV
    applet_data_dict = extract_applet_data_dict(response_data)
    applet_data_dict.to_csv(output_path / 'applet_data_dict.csv', index=False)
    print("=" * 50)
    print("applet_data_dict.csv file saved")
    print("=" * 50)


    # Reorganizes subscales from columns to rows
    subscale_tranformed_data_init = subscale_transform_long_format(response_data)
    if subscale_tranformed_data_init is not None:
        subscale_tranformed_data = subscale_tranformed_data_init.copy()
    else: 
        subscale_tranformed_data = response_data.copy()


    # format all epoch datetime columns to human readable timestamp
    for col in ['activity_start_time_utc', 'activity_end_time_utc', 'activity_schedule_start_time_utc']:
        subscale_tranformed_data[col] = format_epochtime(subscale_tranformed_data, col)

    # creates a new cleaned version of the response column - formatted_response
    subscale_tranformed_data['formatted_response'] = format_response(subscale_tranformed_data)

    # created 2 new columns, extracting the exact selection of the response and corresponding score
    subscale_tranformed_data['response_values'], subscale_tranformed_data['response_scores'] = response_value_score_mapping(subscale_tranformed_data)

    # write long format output with all the cleaned data to a csv
    subscale_tranformed_data.to_csv(output_path/'report_response_formatted.csv', index=False)
    print("=" * 50)
    print("report_response_formatted.csv file saved")
    print("=" * 50)

    # Apply the function to process data into wide format and save output to csv
    data_wide = widen_data(subscale_tranformed_data, final_column_list)
    data_wide.to_csv(os.path.join(output_path, 'report_response_formatted_widened.csv'), index=False)
    print("=" * 50)
    print("report_response_formatted_widened.csv file saved")
    print("=" * 50)


    response_wide_split_by_activity(subscale_tranformed_data, final_column_list, output_path)
    print("=" * 50)
    print("response_wide_split_by_activity folder created and split files saved within")
    print("=" * 50)



if __name__ == "__main__":
    main()



