import os
import base64
import json
import re
from flask import Flask, request, redirect, session, render_template
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from pickle import dumps, loads
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')  # Read from .env

# OAuth2 client info
CLIENT_ID = os.getenv('CLIENT_ID')  # Read from .env
CLIENT_SECRET = os.getenv('CLIENT_SECRET')  # Read from .env
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Set up Gmail API credentials
# credentials = Credentials.from_authorized_user_file('credentials.json', ['https://www.googleapis.com/auth/gmail.readonly'])

# Function to retrieve the longest from email address
def get_longest_from_address(emails):
    matching_emails = [email for email in emails if email['domain'] == email['dkimDomain']]
    if matching_emails:
        longest_address = max(matching_emails, key=lambda email: len(email['from']))['from']
    return longest_address

# Function to retrieve the longest to email address
def get_longest_to_address(emails):
    longest_address = max(emails, key=lambda email: len(email['to']))['to']
    return longest_address

# Function to retrieve the longest message ID
def get_longest_message_id(emails):
    longest_message_id = max(emails, key=lambda email: len(email['messageId']))['messageId']
    return longest_message_id

def get_dkim_domains_with_more_than_one_dkim_selector(emails):
    dkim_domains = {} # Map of domains to selectors
    for email in emails:
        if email['dkimDomain'] in dkim_domains:
            if(email['dkimSelector'] not in dkim_domains[email['dkimDomain']]):
                dkim_domains[email['dkimDomain']].append(email['dkimSelector'])
        else:
            dkim_domains[email['dkimDomain']] = [email['dkimSelector']]
    domains_to_delete = [domain for domain in dkim_domains if len(dkim_domains[domain]) < 2]
    for domain in domains_to_delete:
        del dkim_domains[domain]
    return dkim_domains

# Function to retrieve the last N emails
def retrieve_emails(limit, pageToken=None):
    credentials_dict = session['credentials']
    credentials = Credentials.from_authorized_user_info(credentials_dict)
    service = build('gmail', 'v1', credentials=credentials)
    results: dict = service.users().messages().list(userId='me', maxResults=limit, pageToken=pageToken).execute()
    emails: list = []
    for message in results['messages']:
        msg_id = message['id']
        email_data = service.users().messages().get(userId='me', id=msg_id).execute()
        
        # Extracting the data you need from email_data
        # For example, snippet and headers:
        snippet = email_data.get('snippet')
        headers = email_data.get('payload', {}).get('headers', [])
        print(headers)
        subject, from_email, dkim_selector, message_id, domain = '', '', '', '', ''
        to_email = ''
        for header in headers:
            if header['name'] == 'Subject':
                subject = header['value']
            elif header['name'] == 'From':
                try:
                    from_email = header['value'].split('<')[1].rstrip('>')
                except IndexError:
                    from_email = header['value']
                print(from_email)
                domain = from_email.split('@')[1]
            elif header['name'] == 'To':
                try:
                    to_email = header['value'].split('<')[1].rstrip('>')
                except IndexError:
                    to_email = header['value']
            elif header['name'] == 'DKIM-Signature':
                dkim_selector = header['value'].split('s=')[1].split(';')[0]
                dkim_domain = header['value'].split('d=')[1].split(';')[0]
            elif header['name'] == 'Message-ID':
                message_id = header['value']

        emails.append({
            'id': msg_id,
            'threadId': message['threadId'],
            'snippet': snippet,
            'subject': subject,
            'from': from_email,
            'to': to_email,
            'dkimSelector': dkim_selector,
            'messageId': message_id,
            'domain': domain,
            'dkimDomain': dkim_domain
        })  
    print(emails)
    for email in emails:
        print(f"Selector: {email['dkimSelector']}, Domain: {email['domain']}, dkimDomains: {email['dkimDomain']}")
    if 'nextPageToken' in results:
        limit -= len(results['messages'])
        if(limit > 0):
            emails.extend(retrieve_emails(limit, results['nextPageToken']))
    return emails

def credentials_to_dict(credentials):
    return {'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes}

@app.route('/authorize')
def authorize():
    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uris": ["http://localhost:5000/oauth2callback", "http://127.0.0.1:5000/oauth2callback"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth", "redirect_uri": "http://127.0.0.1:5000/oauth2callback",
                "redirect_uri": "http://127.0.0.1:5000/oauth2callback", 
                "token_uri": "https://accounts.google.com/o/oauth2/token",
            }
        },
        scopes=SCOPES,
        state=session.new
    )
    flow.redirect_uri = "http://127.0.0.1:5000/oauth2callback";
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')

    session['state'] = state

    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = session['state']

    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uris": ["http://localhost:5000/oauth2callback", "http://127.0.0.1:5000/oauth2callback"],
                "redirect_uri": "http://127.0.0.1:5000/oauth2callback",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://accounts.google.com/o/oauth2/token",
            }
        },
        scopes=SCOPES,
        state=state
    )

    flow.redirect_uri = "http://127.0.0.1:5000/oauth2callback";
    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    session['credentials'] = credentials_to_dict(credentials)
    service = build('gmail', 'v1', credentials=credentials)    
    return render_template('index.html')

# Route for the home page
@app.route('/')
def home():
    return render_template('index.html')

# Route for retrieving and displaying the results
@app.route('/results')
def results():
    limit = 500  # Number of emails to retrieve
    emails = retrieve_emails(limit)
    print("Emails: ", emails);
    longest_from_address = get_longest_from_address(emails)
    longest_from_address = f"{longest_from_address} (Length: {len(longest_from_address)})"
    longest_to_address = get_longest_to_address(emails)
    longest_to_address = f"{longest_to_address} (Length: {len(longest_to_address)})"
    longest_message_id = get_longest_message_id(emails)
    longest_message_id = f"{longest_message_id} (Length: {len(longest_message_id)})"
    multi_selectors = get_dkim_domains_with_more_than_one_dkim_selector(emails)

    return render_template('results.html', 
                           longest_from_address=longest_from_address, 
                           longest_to_address=longest_to_address, 
                           longest_message_id=longest_message_id, 
                           multi_selectors=multi_selectors)

if __name__ == '__main__':
    app.run('127.0.0.1', debug=True)
    
