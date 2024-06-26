import requests
from requests.adapters import HTTPAdapter, Retry
import json
from bs4 import BeautifulSoup
import zipfile
import csv
import io
from default_repo.utils.bgg_utils import folder_paths, gcp_authenticate
import os
import shutil

if 'custom' not in globals():
    from mage_ai.data_preparation.decorators import custom
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test

def create_id_list(bgg_list_path: str, csv_path: str) -> None:
    # Create id list of bgg things
    with bucket.blob(csv_path).open('r',newline='') as f:
        csvreader = csv.reader(f)
        ids: list[str] = [row[0] for row in csvreader]

    logging.info(f"Extracted {len(ids)-1} ids")
    
    id_path: str = f"{bgg_list_path}/bgg_id.csv"
    with bucket.blob(id_path).open('w') as f:
        for id in ids:
            f.write(f"{id}\n")
    
    logging.info(f"Created bgg_id.csv at {id_path}")

    return id_path

def download_bgg_list(bgg_list_path: str, session) -> str:
    # Locate download link in page, the link changes daily
    r = session.get("https://boardgamegeek.com/data_dumps/bg_ranks")
    soup = BeautifulSoup(r.text, 'html.parser')
    zip_url = soup.find('a',string="Click to Download")['href']
    
    local_temp_path = f"/home/src/default_repo/temp/{bgg_list_path}"

    try:
        r = requests.get(zip_url)
        r.raise_for_status()
  
        with io.BytesIO(r.content) as zip_buffer:
            with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                file_name = zip_ref.namelist()[0]
                zip_ref.extractall(local_temp_path)
        logging.info(f"{file_name} downloaded extracted locally to {local_temp_path}")
    except Exception as e:
        logging.error(f"{file_name} failed to download: {e}", exc_info=True)
        raise

    csv_path = f"{bgg_list_path}/{file_name}"
    blob = bucket.blob(csv_path)
    blob.upload_from_filename(f"{local_temp_path}/{file_name}")
    logging.info(f"{file_name} uploaded to {csv_path}")

    return csv_path

def login_bgg(bgg_list_path: str) -> str:
    with requests.Session() as s:
        logging.info(f'Creating login session to BoardGameGeek')
        retries = Retry(total=2, backoff_factor=2, status_forcelist=[400], allowed_methods=["POST"])
        s.mount('https://', HTTPAdapter(max_retries=retries))
        
        body=json.dumps({"credentials": {"username": "apidummy", "password": "apidummy"}})
        headers={
        'authority': 'boardgamegeek.com',
        'content-type': 'application/json',
        'origin': 'https://boardgamegeek.com',
        'referer': 'https://boardgamegeek.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }

        try:
            p = s.post('https://boardgamegeek.com/login/api/v1', data=body, headers=headers)
            p.raise_for_status()
            logging.info(f"Login successful with status code {p.status_code}")
        except Exception as e:
            logging.error(f"An error occurred: {e}", exc_info=True)
            raise

    csv_path = download_bgg_list(bgg_list_path, session=s)
    return csv_path

def recreate_folders(path: str) -> None:
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    return None

@custom
def main(*args, **kwargs):
    global logging
    logging = kwargs.get('logger')

    global bucket
    bucket, _, _ = gcp_authenticate()
    logging.info(f"Google Cloud Platform authentication successful")

    _, bgg_list_path, raw_data_path, stage_data_path, local_temp_path = folder_paths()

    recreate_folders(f"{local_temp_path}/{raw_data_path}")
    recreate_folders(f"{local_temp_path}/{stage_data_path}")

    csv_path = login_bgg(bgg_list_path)
    id_path = create_id_list(bgg_list_path, csv_path)
    return id_path