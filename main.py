import streamlit as st
import re
import nltk
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

# Authenticate Google Drive using Service Account
@st.cache_resource
def authenticate_drive():
    SERVICE_ACCOUNT_FILE = 'C:\\Users\\User\\Documents\\GitHub\\Recruiting-Tool\\recruiting-tool-443220-eb3e27f79431.json'
    SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']
    credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('drive', 'v3', credentials=credentials)
    return service

# Call the authenticate function
drive_service = authenticate_drive()

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
            "Name": "", "City": "", "Skills": "", "Highest Education": "",
            "Years of Experience": "", "Phone Number": "", "Email": "", 
            "Date Added": str(datetime.now()), "Link": ""
        }
        lines = summary.split("\n")
        for line in lines:
            if line.startswith("Name:"):
                summary_dict["Name"] = line.split(":", 1)[1].strip()
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

# Function to load JSON data from Google Drive
def load_json(service, folder_id):
    results = service.files().list(q=f"'{folder_id}' in parents and trashed=false").execute()
    files = results.get('files', [])
    json_file = next((file for file in files if file['name'] == 'summaries.json'), None)
    if json_file:
        file_id = json_file['id']
        file_content = service.files().get_media(fileId=file_id).execute()
        return json.loads(file_content.decode('utf-8')), file_id
    else:
        return [], None

# Function to save JSON data to Google Drive
def save_json(service, folder_id, data, file_id=None):
    json_data = io.BytesIO(json.dumps(data, indent=4).encode('utf-8'))
    file_metadata = {'name': 'summaries.json', 'parents': [folder_id]}
    media = MediaIoBaseUpload(json_data, mimetype='application/json')
    if file_id:
        file = service.files().update(fileId=file_id, addParents=folder_id, media_body=media).execute()
    else:
        file = service.files().create(body=file_metadata, media_body=media).execute()
    return file

# Function to upload a file to Google Drive
def upload_to_drive(service, folder_id, file_path):
    file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(open(file_path, 'rb').read()), mimetype='application/pdf' if file_path.endswith('.pdf') else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    file = service.files().create(body=file_metadata, media_body=media).execute()
    return file['id']

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

# Main App
def main():
    st.title("Recruiting Tool with Resume Summarization and Search")

    # Tabs for Upload and Search
    tab1, tab2 = st.tabs(["Upload Resumes", "Search Resumes"])

    # Folder IDs
    main_folder_id = '1mcDvXZNMC-CMiJ73onGw5EjYYrA1-tEn'
    resume_folder_id = '1E0Hzbfql_ARQYlzScvUsaP1biSn88-PN'
    json_folder_id = '1r-jpOI838VAAHtyDNQVpqyr0_pa7fNzy'

    with tab1:
        st.header("Upload Resumes")
        uploaded_files = st.file_uploader("Upload PDF/DOCX files or a folder of resumes", accept_multiple_files=True, type=["pdf", "docx"])

        if st.button("Process Resumes"):
            if uploaded_files:
                if not os.path.exists("temp"):
                    os.mkdir("temp")
                data, file_id = load_json(drive_service, json_folder_id)

                for uploaded_file in uploaded_files:
                    file_path = f"temp/{uploaded_file.name}"
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getvalue())
                    uploaded_file_id = upload_to_drive(drive_service, resume_folder_id, file_path)
                    if uploaded_file_id:
                        st.success(f"File {uploaded_file.name} uploaded successfully to Google Drive.")
                    
                    text = extract_text_from_file(file_path)
                    summary = summarize_resume(text)
                    if summary:
                        summary_data = json.loads(summary)
                        summary_data["Link"] = f"https://drive.google.com/file/d/{uploaded_file_id}/view"
                        if not is_duplicate(data, summary_data["Name"], summary_data["Email"], summary_data["Phone Number"]):
                            data.append(summary_data)
                            save_json(drive_service, json_folder_id, data, file_id)
                            st.text_area("Summary", summary, height=300)
                        else:
                            st.warning(f"Resume {uploaded_file.name} already exists in the system.")

            else:
                st.warning("Please upload files to proceed.")

    with tab2:
        st.header("Search Resumes")
        job_title = st.text_input("Enter Job Title", "")
        keywords = st.text_input("Enter Keywords", "")
        date_range = st.date_input("Select Date Range", [])

        # Load data from Google Drive
        data, _ = load_json(drive_service, json_folder_id)

    # Filter data based on search criteria
        if data:
            search_results = data

            # Filter by job title
            if job_title:
                search_results = search_results = [entry for entry in search_results if fuzzy_match(job_title, entry.get("Years of Experience", ""), 80)]

            # Filter by keywords in the skills
            if keywords:
                search_results = [entry for entry in search_results if fuzzy_match(keywords, entry.get("Skills", ""), 80)]

            # Filter by date range (if specified)
            if date_range and len(date_range) == 2:
                start_date, end_date = date_range
                search_results = [entry for entry in search_results if start_date <= datetime.fromisoformat(entry["Date Added"][:10]).date() <= end_date]

            # Display results
            if search_results:
                st.write(search_results)
            else:
                st.info("No matching resumes found.")
        else:
            st.info("No data available to search.")




if __name__ == "__main__":
    main()
