#!/usr/bin/env python
"""MixPanel to MailChimp Email Loaderator"""

import base64
import logging
import urllib2

from google.cloud import storage
from google.appengine.api import app_identity
import googleapiclient.discovery

from flask import Flask
from mailchimp3 import MailChimp
from mixpanel import Mixpanel
import requests


BUCKET              = '...'                     # noqa: E221
KMS_LOCATION        = 'global'                  # noqa: E221
KMS_KEYRING         = '...'                     # noqa: E221
MAILCHIMP_CRYPTOKEY = 'mailchimp'               # noqa: E221
MAILCHIMP_API_FILE  = 'mailchimp.encrypted'     # noqa: E221
MIXPANEL_CRYPTOKEY  = 'mixpanel'                # noqa: E221
MIXPANEL_API_FILE   = 'mixpanel.encrypted'      # noqa: E221

# General List
MAILCHIMP_LISTID             = '...'     # noqa: E221
# General Weekly List
MAILCHIMP_WEEKLY_LISTID      = '...'     # noqa: E221
# Property-based List
MAILCHIMP_PROPERTY_LISTID    = '...'     # noqa: E221
PROPERTY_WHERE_CLAUSE        = '(properties["some property"] >= some_value)'  # noqa: E221, E501


app = Flask(__name__)


def _decrypt(project_id, location, keyring, cryptokey, cipher_text):
    """Decrypts and returns string from given cipher text."""
    logging.info('Decrypting cryptokey: {}'.format(cryptokey))
    kms_client = googleapiclient.discovery.build('cloudkms', 'v1')
    name = 'projects/{}/locations/{}/keyRings/{}/cryptoKeys/{}'.format(
        project_id, location, keyring, cryptokey)
    cryptokeys = kms_client.projects().locations().keyRings().cryptoKeys()
    request = cryptokeys.decrypt(
        name=name, body={'ciphertext': cipher_text.decode('utf-8')})
    response = request.execute()
    return base64.b64decode(response['plaintext'])


def _download_output(output_bucket, filename):
    """Downloads the output file from GCS and returns it as a string."""
    logging.info('Downloading output file')
    client = storage.Client()
    bucket = client.get_bucket(output_bucket)
    output_blob = (
        'keys/{}'
        .format(filename))
    return bucket.blob(output_blob).download_as_string()


def get_credentials(cryptokey, filename):
    """Fetches credentials from KMS returning a decrypted API key."""
    credentials_enc = _download_output(BUCKET, filename)
    credentials_dec = _decrypt(app_identity.get_application_id(),
                               KMS_LOCATION,
                               KMS_KEYRING,
                               cryptokey,
                               credentials_enc)
    return credentials_dec


def get_new_users(key, where_clause=False):
    """Gets new users from MixPanel."""
    logging.info('Making an API call to MixPanel')
    api = Mixpanel(api_secret=str(key).strip())
    mixpanel_data = {}
    try:
        if where_clause:
            mixpanel_data = api.request(['engage'], {'where': where_clause})
            """  # noqa: E501
              The $created People Property appears to have dissappeared.  :(
              Until it is back, we cannot filter by it, not sure if they even support this
              in the 'where' clause.
              Doc: https://mixpanel.com/help/reference/data-export-api#people-analytics
              Reached out here: https://twitter.com/mediocrity/status/871543709539508229
            'where': '(properties["$created"]) < XXXX-YY-ZZ'
            """
        else:
            mixpanel_data = api.request(['engage'])
    except (urllib2.URLError, urllib2.HTTPError) as error:
        logging.exception('An error occurred: {0}'.format(error))

    # Pagination with weird MixPanel API
    session_id = mixpanel_data['session_id']    # Unsure if it stays the same
    current_page = mixpanel_data['page']
    current_total = mixpanel_data['total']
    while current_total >= 1000:
        logging.info('Page: {0}'.format(current_page + 1))
        try:
            mixpanel_data['results'].append(api.request(['engage'], {
                'page': current_page + 1,
                'session_id': session_id
            })['results'])
        except (urllib2.URLError, urllib2.HTTPError) as error:
            logging.error('An error occurred: {0}'.format(error))
            pass

    return mixpanel_data


def cleanup_mixpanel_data(results):
    """Cleans up the MixPanel data."""
    cleaned_up_data = {}

    for user in results['results']:
        try:
            cleaned_up_data[user['$properties']['$email']] = user['$properties']['$name']   # noqa: E501
        # Missing values are entirely possible, this is analytics data!
        except (KeyError, ValueError) as error:
            logging.error('An error occurred cleaning up data: {0}'.format(error))          # noqa: E501
            logging.error('User data: {0}'.format(user))
            pass

    return cleaned_up_data


def push_new_users_to_mailchimp(key, new_users, list_id):
    """Push new users to MailChimp new user list."""
    logging.info('Making an API call to MailChimp')
    logging.info('Pushing New Users to list: {0}'.format(list_id))
    client = MailChimp('apikey', str(key).strip())
    emails_added_for_debugging = []

    for email, full_name in new_users.iteritems():
        name_split = full_name.split()
        try:
            client.lists.members.create(list_id, {
                'email_address': email,
                'status': 'subscribed',
                'merge_fields': {
                    'FNAME': name_split[0],
                    'LNAME': name_split[-1],
                },
            })

            emails_added_for_debugging.append(email)

            """  # noqa: E501
            Not the ideal but create_or_update doesn't help either.
            Might need to move away from the lovely mailchimp3 library or path it to
            deal with MailChimp API throwing a 400 on create if the member exists.
            """
        except requests.exceptions.HTTPError as error:
            logging.error('Error: {0}'.format(error))
            logging.error('Member: {0}, is already on the list: {1}'.format(email, list_id))    # noqa: E501
            pass

    logging.info('Emails added for debugging to list: {0}, {1}'.format(list_id, emails_added_for_debugging))
    return


def runit():
    """Runs the task."""
    mixpanel_creds = get_credentials(MIXPANEL_CRYPTOKEY, MIXPANEL_API_FILE)
    mailchimp_creds = get_credentials(MAILCHIMP_CRYPTOKEY, MAILCHIMP_API_FILE)

    new_users = get_new_users(mixpanel_creds)
    new_users_formatted = cleanup_mixpanel_data(new_users)
    property_based_users = get_new_users(mixpanel_creds, PROPERTY_WHERE_CLAUSE)                              # noqa: E501
    property_based_users_formatted = cleanup_mixpanel_data(property_based_users)                             # noqa: E501
    push_new_users_to_mailchimp(mailchimp_creds, new_users_formatted, MAILCHIMP_LISTID)                      # noqa: E501
    push_new_users_to_mailchimp(mailchimp_creds, new_users_formatted, MAILCHIMP_WEEKLY_LISTID)               # noqa: E501
    push_new_users_to_mailchimp(mailchimp_creds, property_based_users_formatted, MAILCHIMP_PROPERTY_LISTID)  # noqa: E501
    return 'Completed'


@app.route('/run')
def run():
    return runit()


@app.errorhandler(500)
def server_error(e):
    # Log the error and stacktrace.
    logging.exception('An error occurred during a request.')
    return 'An internal error occurred.', 500
