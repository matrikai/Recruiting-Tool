import streamlit as st
import pandas as pd
import re
import uuid
import nltk
import shutil
from pathlib import Path
from datetime import datetime
from fuzzywuzzy import fuzz
from PyPDF2 import PdfReader
from docx import Document
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
import io
import json
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from groq import Groq
import ssl
import certifi
import httplib2



st.set_page_config(layout="wide")  # Set layout to wide for better visibility
# Ensure SSL/TLS compatibility
try:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    # st.info("SSL/TLS context created successfully.")
except Exception as ssl_setup_error:
    st.error(f"Error setting up SSL context: {ssl_setup_error}")
# Setting up SSL context for secure connections
# ssl._create_default_https_context = ssl.create_default_context(cafile=certifi.where())
# Create an Http instance with enforced SSL/TLS settings
# httplib2.Http.force_tls_version = ssl.PROTOCOL_TLSv1_2

# Authenticate Google Drive using Service Account
@st.cache_resource
def authenticate_drive():
    SERVICE_ACCOUNT_FILE = 'C:\\Users\\User\\Documents\\GitHub\\Recruiting-Tool\\recruiting-tool-443220-eb3e27f79431.json'
    SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']
    credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('drive', 'v3', credentials=credentials)
    return service

# Call the authenticate function once
if "drive_service" not in st.session_state:
    st.session_state["drive_service"] = authenticate_drive()
drive_service = st.session_state["drive_service"]
import time
from googleapiclient.errors import HttpError

def execute_request_with_retry(request, retries=3):
    """Executes Google API requests with retry logic and error logging."""
    for attempt in range(retries):
        try:
            return request.execute()
        except ssl.SSLError as ssl_error:
            st.error(f"SSL Error on attempt {attempt + 1}: {ssl_error}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise ssl_error
        except HttpError as http_error:
            st.error(f"HTTP Error on attempt {attempt + 1}: {http_error}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise http_error
        except Exception as e:
            st.error(f"Unexpected error on attempt {attempt + 1}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise e


# Function for removing stop words
def remove_stopwords(text):
    nltk.download("stopwords", quiet=True)
    stop = nltk.corpus.stopwords.words("english")
    return ' '.join(word for word in text.split() if word not in stop)

# Function for removing URLs
def remove_urls(text):
    url_pattern = r'(http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+|www\.[a-zA-Z0-9.-]+\.[A-Z|a-z]{2,})'
    cleaned_text = re.sub(url_pattern, '', text)
    return re.sub(r'\s+', ' ', cleaned_text)

# Helper function to extract text from files
def extract_text_from_file(file_path):
    if file_path.endswith(".pdf"):
        reader = PdfReader(file_path)
        text = " ".join(page.extract_text() for page in reader.pages if page.extract_text())
    elif file_path.endswith(".docx"):
        doc = Document(file_path)
        text = " ".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text)
    else:
        text = None
    if text:
        text = remove_urls(text)
        text = remove_stopwords(text)
    return text

# Function to summarize a resume
def summarize_resume(resume_text):
    client = Groq(api_key="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")
    prompt = f"""Summarize this resume text into the following format:
    Name: 
    Job Title:
    City: 
    Skills: 
    Highest Education: 
    Years of Experience: 
    Phone Number: 
    Email: 

    {resume_text}"""
    completion = client.chat.completions.create(
        model="llama-3.1-70b-versatile",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.7,
        max_tokens=8000,
        top_p=1,
        stream=True
    )

    summary = ""
    for chunk in completion:
        summary += chunk.choices[0].delta.content or ""

    try:
        summary_dict = {
            "Name": "", "Job Title": "", "City": "", "Skills": "", "Highest Education": "",
            "Years of Experience": "", "Phone Number": "", "Email": "", 
            "Date Added": str(datetime.now()), "Link": ""
        }
        lines = summary.split("\n")
        for line in lines:
            if line.startswith("Name:"):
                summary_dict["Name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Job Title:"):  
                summary_dict["Job Title"] = line.split(":", 1)[1].strip()
            elif line.startswith("City:"):
                summary_dict["City"] = line.split(":", 1)[1].strip()
            elif line.startswith("Skills:"):
                summary_dict["Skills"] = line.split(":", 1)[1].strip()
            elif line.startswith("Highest Education:"):
                summary_dict["Highest Education"] = line.split(":", 1)[1].strip()
            elif line.startswith("Years of Experience:"):
                summary_dict["Years of Experience"] = line.split(":", 1)[1].strip()
            elif line.startswith("Phone Number:"):
                summary_dict["Phone Number"] = line.split(":", 1)[1].strip()
            elif line.startswith("Email:"):
                summary_dict["Email"] = line.split(":", 1)[1].strip()

        return json.dumps(summary_dict, indent=4)
    except Exception as e:
        print(f"Error parsing summary: {e}")
        return None

def load_json(service, folder_id):
    """Loads JSON data from Google Drive."""
    service = st.session_state["drive_service"]
    try:
        results = execute_request_with_retry(
            service.files().list(q=f"'{folder_id}' in parents and trashed=false")
        )
        files = results.get('files', [])
        json_file = next((file for file in files if file['name'] == 'summaries.json'), None)
        if json_file:
            file_id = json_file['id']
            file_content = execute_request_with_retry(
                service.files().get_media(fileId=file_id)
            )
            return json.loads(file_content.decode('utf-8')), file_id
        return [], None
    except ssl.SSLError as ssl_error:
        st.error(f"SSL Error encountered: {ssl_error}")
        return [], None
    except Exception as e:
        st.error(f"Error loading JSON: {e}")
        return [], None


def save_json(service, folder_id, data, file_id=None):
    """Saves JSON data to Google Drive."""
    service = st.session_state["drive_service"]
    try:
        json_data = io.BytesIO(json.dumps(data, indent=4).encode('utf-8'))
        file_metadata = {'name': 'summaries.json', 'parents': [folder_id]}
        media = MediaIoBaseUpload(json_data, mimetype='application/json')

        if file_id:
            file = execute_request_with_retry(
                service.files().update(fileId=file_id, addParents=folder_id, media_body=media)
            )
        else:
            file = execute_request_with_retry(
                service.files().create(body=file_metadata, media_body=media)
            )
        return file
    except ssl.SSLError as ssl_error:
        st.error(f"SSL Error encountered while saving: {ssl_error}")
    except Exception as e:
        st.error(f"Error saving JSON: {e}")


def upload_to_drive(service, folder_id, file_path):
    """Uploads a file to Google Drive."""
    service = st.session_state["drive_service"]
    try:
        # Prepare metadata
        file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
        
        # Use an in-memory buffer to prevent closed file errors
        with open(file_path, 'rb') as f:
            file_content = f.read()
        buffer = io.BytesIO(file_content)

        # Set the correct MIME type based on the file extension
        mime_type = (
            'application/pdf' if file_path.endswith('.pdf')
            else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

        # Create a media upload object
        media = MediaIoBaseUpload(buffer, mimetype=mime_type)

        # Execute the file upload
        file = execute_request_with_retry(
            service.files().create(body=file_metadata, media_body=media)
        )
        return file['id']
    except ssl.SSLError as ssl_error:
        st.error(f"SSL Error during file upload: {ssl_error}")
    except Exception as e:
        st.error(f"Error uploading file: {e}")


# Function to check if a resume is already uploaded based on matching fields
def is_duplicate(data, name, email, phone):
    for entry in data:
        if fuzz.ratio(entry.get("Name", ""), name) > 80 and \
           fuzz.ratio(entry.get("Email", ""), email) > 80 and \
           fuzz.ratio(entry.get("Phone Number", ""), phone) > 80:
            return True
    return False


# Helper function to match with a given threshold
def fuzzy_match(input_text, target_text, threshold=80):
    if fuzz.partial_ratio(input_text.lower(), target_text.lower()) >= threshold:
        return True
    return False

# Update JSON structure to include shortlisted field
def initialize_json(data):
    for entry in data:
        if "shortlisted" not in entry:
            entry["shortlisted"] = False
    return data

#Preserve app state
if "search_results" not in st.session_state:
    st.session_state["search_results"] = []
if "selected_rows" not in st.session_state:
    st.session_state["selected_rows"] = []

# Function to convert JSON data to DataFrame
def json_to_dataframe(data):
    df = pd.DataFrame(data)
    df = df[~df["shortlisted"]]  # Exclude shortlisted resumes from display
    return df

# Main App
# Function to update shortlisted status from dropdowns
def update_shortlisted_entries(data, selected_ids):
    for entry in data:
        if entry["id"] in selected_ids:
            entry["shortlisted"] = True
    return data

# Main App
def main():
    st.title("Recruiting Tool with Resume Shortlisting and Export")

    # Sidebar
    st.sidebar.header("Actions")
    uploaded_files = st.sidebar.file_uploader("Upload PDF/DOCX Files", accept_multiple_files=True, type=["pdf", "docx"])
    process_button = st.sidebar.button("Process Resumes")
    download_csv_button = st.sidebar.empty()  # Placeholder for CSV download button
    download_shortlisted_button = st.sidebar.empty()  # Placeholder for shortlisted download button

    # Folder IDs
    main_folder_id = '1mcDvXZNMC-CMiJ73onGw5EjYYrA1-tEn'
    resume_folder_id = '1E0Hzbfql_ARQYlzScvUsaP1biSn88-PN'
    json_folder_id = '1r-jpOI838VAAHtyDNQVpqyr0_pa7fNzy'

    # Base directory for temporary files
    base_dir = Path(os.getenv('BASE_DIR', Path.cwd())) / "temp"

    # Load JSON data
    data, file_id = load_json(drive_service, json_folder_id)
    data = initialize_json(data)

    # Center area for search and filters
    col1, col2, col3 = st.columns([3, 2, 2])

    with col1:
        job_title = st.text_input("Enter Job Title", placeholder="e.g., Software Engineer, Data Scientist")
        keywords = st.text_input("Enter Keywords", placeholder="e.g., Python, Machine Learning, Data Analysis")

    with col2:
        date_range = st.date_input("Select Date Range", [])

    # Disable the search button if either job title or keywords is empty
    search_button = st.button("Search", disabled=not job_title or not keywords)

    # Process uploaded files
    if process_button:
        if uploaded_files:
            temp_folder = base_dir
            temp_folder.mkdir(parents=True, exist_ok=True)

            try:
                for uploaded_file in uploaded_files:
                    file_path = temp_folder / uploaded_file.name
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getvalue())

                    text = extract_text_from_file(str(file_path))
                    summary = summarize_resume(text)

                    if summary:
                        summary_data = json.loads(summary)
                        summary_data["Date Added"] = str(datetime.now())
                        summary_data["shortlisted"] = False
                        summary_data["id"] = str(uuid.uuid4())

                        # Check for duplicates
                        if not is_duplicate(data, summary_data["Name"], summary_data["Email"], summary_data["Phone Number"]):
                            # Upload file to Google Drive only if not a duplicate
                            uploaded_file_id = upload_to_drive(drive_service, resume_folder_id, str(file_path))

                            if uploaded_file_id:
                                st.sidebar.success(f"File {uploaded_file.name} uploaded successfully to Google Drive.")
                                summary_data["Link"] = f"https://drive.google.com/file/d/{uploaded_file_id}/view"

                            # Add the summary to the data
                            data.append(summary_data)
                            save_json(drive_service, json_folder_id, data, file_id)
                            # st.sidebar.text_area("Summary", summary, height=300)
                        else:
                            st.sidebar.warning(f"Resume {uploaded_file.name} already exists in the system.")
            except Exception as e:
                st.sidebar.error(f"An error occurred during processing: {e}")
            finally:
                if temp_folder.exists():
                    shutil.rmtree(temp_folder)
        else:
            st.sidebar.warning("Please upload files to proceed.")

    # Filter data based on search criteria when search button is clicked
    if search_button:
        # Store search results in session state to persist between interactions
        if "search_results" not in st.session_state:
            st.session_state["search_results"] = []
        search_results = [entry for entry in data if not entry["shortlisted"]]  # Exclude shortlisted resumes

        if job_title:
            search_results = [entry for entry in search_results if fuzzy_match(job_title, entry.get("Job Title", ""), 80)]

        if keywords:
            search_results = [entry for entry in search_results if fuzzy_match(keywords, entry.get("Skills", ""), 80)]

        if date_range and len(date_range) == 2:
            start_date, end_date = date_range
            search_results = [
                entry for entry in search_results
                if start_date <= datetime.fromisoformat(entry["Date Added"][:10]).date() <= end_date
            ]

        # Store the filtered results in session state
        st.session_state["search_results"] = search_results

    if "search_results" in st.session_state and st.session_state["search_results"]:
        search_results = st.session_state["search_results"]

        # Prepare the DataFrame for display
        results_df = pd.DataFrame(search_results)
        results_df = results_df.rename(columns={"shortlisted": "Shortlist"})  # Rename for better display
        # Select columns to display and exclude the 'id' column
        columns_to_display = [col for col in results_df.columns if col not in ['id', 'Job Title']]
        # Editable table for user interaction
        edited_df = st.data_editor(
            results_df[columns_to_display],
            use_container_width=True,
            key="editable_table",  # Ensure persistence of edits
        )

        # Match by either Email or Phone Number
        for idx, row in edited_df.iterrows():
            # Check if 'Email' exists in row and match by Email or Phone
            if "Email" in row and row["Email"]:
                match = next((entry for entry in data if entry["Email"] == row["Email"]), None)
            elif "Phone Number" in row and row["Phone Number"]:
                match = next((entry for entry in data if entry["Phone Number"] == row["Phone Number"]), None)
            else:
                match = None  # In case neither Email nor Phone is available
    
            if match:
                match["shortlisted"] = row["Shortlist"]        

        # Save updates back to JSON
        if st.button("Update Shortlist"):
            save_json(drive_service, json_folder_id, data, file_id)
            st.success("Shortlist updated successfully!")    

            #  # Check if there are any results to display
            # if results_df.empty:
            #     st.info("No matching resumes found based on your search criteria.")
            # else:
            #     # Display the table if there are results
            #     st.dataframe(results_df)

            # Add buttons for downloading results
            csv_data = results_df.to_csv(index=False)
            download_csv_button.download_button("Download Search Results as CSV", data=csv_data, file_name="search_results.csv", mime="text/csv")

            shortlisted_resumes = [entry for entry in data if entry["shortlisted"]]
            if shortlisted_resumes:
                shortlisted_df = pd.DataFrame(shortlisted_resumes)
                shortlisted_csv_data = shortlisted_df.to_csv(index=False)
                download_shortlisted_button.download_button(
                    "Download Shortlisted Resumes as CSV",
                    data=shortlisted_csv_data,
                    file_name="shortlisted_resumes.csv",
                    mime="text/csv"
                )
    else:
       # Show this message only if there are no search results after search
       if search_button:
        st.info("No matching resumes found. Please refine your search criteria.")

if __name__ == "__main__":
    main()

