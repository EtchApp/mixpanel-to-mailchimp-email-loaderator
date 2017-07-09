# MixPanel to MailChimp Email Loaderator

I ❤ MixPanel. I also ❤ MailChimp.

But I am sorry MixPanel, you are not MailChimp for Email notifications.

At Etch (do you like places? do you have an iPhone? go download it [here](https://etchapp.com/)) we would prefer to use MailChimp for Email notifications given the extensibility offered by MailChimp as compared to MixPanel.

There is a bunch of snake oil out there to link the two services together (Eww). I would rather own/operate the implementation that we need given how simplistic it is to do and the future optionality.  In addition there doesn't seem to be anything in the open source community to do this so I would like to contribute something back.

## Overview Diagram

![overview diagram](https://github.com/drewrothstein/mixpanel-to-mailchimp-email-loaderator/raw/master/errata/loaderator.png)

## What does it do?

It exports all user's names and emails from MixPanel People properties at the specified run interval and imports them into a MailChimp list.

MailChimp has the ability to trigger a Welcome message on a new member addition to a list and that can be configured if you so choose.

## Where does this run?

This is built to run on the Google App Engine Standard Environment as a Scheduled Task.

## How does it work?

It queries the Data Export API from MixPanel ([doc](https://mixpanel.com/help/reference/data-export-api)) and adds each _new_ user* to a List ([doc](http://developer.mailchimp.com/documentation/mailchimp/reference/lists/members/)).

## Dependencies

See the `requirements.txt` for the list of Python package dependencies.

This relies on successful responses from both MixPanel and MailChimp APIs.

This is built to operate on Google App Engine and thus has dependencies on all of the relevant underlying infrastructure on Google Cloud Platform.

Google Cloud Platform Service Dependencies:
1) App Engine (Standard Environment)
2) Cloud Storage
3) Key Management Service
4) Logging via Stackdriver (not critical)

## Prerequisites

### Accounts

1. MixPanel Account + API Secret.
2. MailChimp Account + API Key.
3. Google Cloud Platform Account.

### System

1. Python 2.7.
2. Working `pip` installation.
3. Installation of `gcloud` SDK and the `dev_appserver.py` loaded into your `PATH` ([doc](https://cloud.google.com/sdk/)).

## Configuration

### Cron Schedule

See `cron.yaml`.

### Secure Key Storage

To securely store the MixPanel API Secret and MailChimp API Key for access by the service from Google App Engine I have chosen to use Google's Key Management Service. Two initial one-time steps need to be completed for this to work.

1) Encrypt and upload the secrets to Google's Key Management Service.
2) Grant the appropriate Service Account access to decrypt the secrets.

Fetch your MixPanel API Secret + MailChimp API Key to be able to proceed.

1) Encrypt Secrets

We will create a Service Account in Google IAM to be able to encrypt / decrypt our secrets (which you could create seaparate encrypt/decrypt accounts and permissions if you would like).

To create a Service Account:
```
$ gcloud --project PROJECT_ID iam service-accounts create SERVICE_ACCOUNT_NAME
$ gcloud --project PROJECT_ID iam service-accounts keys create key.json \
--iam-account SERVICE_ACCOUNT_NAME@PROJECT_ID.iam.gserviceaccount.com
```

This creates a Service Account and a JSON file with the credentials which we can use to encrypt / decrypt our secrets outside of KMS.

One of the easiest ways to interact with Google KMS is to start with the samples from the GCP Samples [Here](https://github.com/GoogleCloudPlatform/python-docs-samples). Once you have this repository cloned, you will create a keyring and cryptokey:
```
$ gcloud --project PROJECT_ID kms keyrings create KEYRING_NAME --location global

$ gcloud --project PROJECT_ID kms keys create mailchimp --location global --keyring KEYRING_NAME --purpose encryption
$ gcloud --project PROJECT_ID kms keys create mixpanel --location global --keyring KEYRING_NAME --purpose encryption

$ gcloud --project PROJECT_ID kms keys add-iam-policy-binding mailchimp --location global \
--keyring KEYRING_NAME --member serviceAccount:KEYRING_NAME@PROJECT_ID.iam.gserviceaccount.com \
--role roles/cloudkms.cryptoKeyEncrypterDecrypter
$ gcloud --project PROJECT_ID kms keys add-iam-policy-binding mixpanel --location global \
--keyring KEYRING_NAME --member serviceAccount:KEYRING_NAME@PROJECT_ID.iam.gserviceaccount.com \
--role roles/cloudkms.cryptoKeyEncrypterDecrypter
```

You will also need to grant the project service account access to decrypt the keys for this implementation. You could use a more secure setup if you would like.
```
gcloud --project PROJECT_ID kms keys add-iam-policy-binding mixpanel --location global \
--keyring KEYRING_NAME --member serviceAccount:PROJECT_ID@appspot.gserviceaccount.com \
--role roles/cloudkms.cryptoKeyDecrypter

gcloud --project PROJECT_ID kms keys add-iam-policy-binding mailchimp --location global \
--keyring KEYRING_NAME --member serviceAccount:PROJECT_ID@appspot.gserviceaccount.com \
--role roles/cloudkms.cryptoKeyDecrypter
```

If you haven't used the KMS service before the SDK will error with a URL to go to to enable:
```
$ gcloud --project PROJECT_ID kms keyrings create KEYRING_NAME --location global
ERROR: (gcloud.kms.keyrings.create) FAILED_PRECONDITION: Google Cloud KMS API has not been used in this project before, or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/cloudkms.googleapis.com/overview?project=... then retry. If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry.
```

Once that is completed, navigate to `kms > api-client` in the GCP Samples repository and create a `doit.sh` with the following content:
```
PROJECTID="PROJECT_ID"
LOCATION=global
KEYRING=KEYRING_NAME
CRYPTOKEY=CRYPTOKEY_NAME
echo 'THE_SECRET' > /tmp/test_file
python snippets.py encrypt $PROJECTID $LOCATION $KEYRING $CRYPTOKEY \
  /tmp/test_file /tmp/test_file.encrypted 
python snippets.py decrypt $PROJECTID $LOCATION $KEYRING $CRYPTOKEY \
  /tmp/test_file.encrypted /tmp/test_file.decrypted
cat /tmp/test_file.decrypted
```

Fill in the `PROJECT_ID` from Google, the `KEYRING_NAME` you chose above, and let's start with the `mailchimp` API Key by inserting it in the place of `THE_SECRET`.

Before you run the script you need to set the environment variable `GOOGLE_APPLICATION_CREDENTIALS` to the path of `key.json` that you generated previously.

This will look something like:
```
export GOOGLE_APPLICATION_CREDENTIALS=FOO/BAR/BEZ/key.json
```

If you now run `bash doit.sh` it should print the API Key and the Encrypted version should be stored in `/tmp/test_file.encrypted`. You can copy this file to somewhere else to temporarily store before we upload and then run the same script with the `mixpanel` API Secret. In the below example I have renamed the files to `mailchimp.encrypted` and `mixpanel.encrypted`.

2) Upload Secrets

Once you have both encrypted secret files we need to upload them to Google Cloud Storage for fetching in App Engine (and eventual decryption). Assuming these files are called `mailchimp.encrypted` and `mixpanel.encrypted`, you would run something like the following:
```
$ gsutil mb -p PROJECT_ID gs://BUCKET_NAME
Creating gs://BUCKET_NAME/...

$ gsutil cp mailchimp.encrypted gs://BUCKET_NAME/
$ gsutil cp mixpanel.encrypted gs://BUCKET_NAME/

$ gsutil mv gs://BUCKET_NAME/mailchimp.encrypted gs://BUCKET_NAME/keys/mailchimp.encrypted
$ gsutil mv gs://BUCKET_NAME/mixpanel.encrypted gs://BUCKET_NAME/keys/mixpanel.encrypted

$ gsutil ls gs://BUCKET_NAME/keys
<BOTH FILES SHOULD BE LISTED HERE>
```

## Building

Initially, you will need to install the dependencies into a `lib` directory with the following command:
```
pip install -t lib -r requirements.txt
```

This `lib` directory is excluded from `git`.

## Local Development

The included `dev_appserver.py` loaded into your `PATH` is the best/easiest way to test before deployment ([doc](https://cloud.google.com/appengine/docs/standard/python/tools/using-local-server))

It can easily be launched with:
```
dev_appserver.py app.yaml
```

And then view `http://localhost:8000/cron` to run the `cron` locally. For this to work you will need to mock the KMS/GCS fetches otherwise you will get a 403 on the call to GCS bucket.

## Deploying

This might be the easiest thing you own / operate as is the case with many things that are built to run on GCP.

Deploy:
```
$ gcloud --project PROJECT_ID app deploy
$ gcloud --project PROJECT_ID app deploy cron.yaml
```

On your first run if this is the first App Engine application you will be prompted to choose a region.

## Testing

No unit tests at this time.

Once deployed, you can hit the `/run` path on the URL.

## Logging

Google's Stackdriver service is sufficient for the logging needs of this service.

To view logs, you can use the `gcloud` CLI:
```
$ gcloud --project PROJECT_ID app logs read --service=default --limit 10
```

If you are not using the `default` project, you will need to change that parameter.

If you want to view the full content of the logs you can use the beta `logging` command:
```
$ gcloud beta logging read "resource.type=gae_app AND logName=projects/[PROJECT_ID]/logs/appengine.googleapis.com%2Frequest_log" --limit 10 --format json
```

Filling in the appropriate `[PROJECT_ID]` from GCP.

You can also see all available logs with the following command:
```
gcloud beta logging logs list
```

## Cost

MixPanel + MailChimp: There are tiers to using both MixPanel and MailChimp, refer to their respective websites for the costs. Their APIs have no costs associated with them.

Google Cloud Platform: The App Engine Standard Environment has three costs associated with it for this project.

1) Compute: Per-instance hour cost ([here](https://cloud.google.com/appengine/pricing#standard_instance_pricing)).
2) Network: Outgoing network traffic ([here](https://cloud.google.com/appengine/pricing#other-resources)).
3) Key Management Service: Key versions + Key use operations ([here](https://cloud.google.com/kms/#cloud-kms-pricing)).

Example Pricing:
Assumptions: We are running the job in Iowa, twice a day, that takes < 1hr each run, network traffic is < 30MB, and we have two active CryptoKeys w/two decryption requests for each run.

1) Compute: The B1 instance is $0.05/hr, we run 24x per day for a total of $1.20/day, (* 30) $36.00/month.
2) Network: We do not exceed 33MB per run and are charged the minimum of $0.12/month.
3) Key Management Service: Two active keys will be $0.12/month with the minimum of $0.03/month for Key use operations.

Estimated total under these conditions: $36.27/month.

Note: If you are utilizing the Free tier (https://cloud.google.com/free/) you get 28 Instance hours per day free on Google App Engine.  Since this job only takes 15m to run (at least under my lists and queries) it will not exceed the free limit and thus Compute costs $0: 15m/run * 24/hours per day = 360m/day = 6 Instance hours per day. Therefore the above estimate is $0.27/m.

## Limits

MixPanel API: Per documentation [here](https://mixpanel.com/help/questions/articles/are-there-rate-limits-for-the-formatted-and-raw-api-endpoints), 60 requests per rolling 60 seconds for up to 5 concurrent connections.

MailChimp API: I couldn't find any numbers from their documentation [here](https://developer.mailchimp.com/documentation/mailchimp/guides/get-started-with-mailchimp-api-3/). The only limit that they mention is, "Each user account is permitted up to 10 simultaneous connections, and you’ll receive an error message if you reach the limit. We don’t throttle based on volume."

## Known Issues

1. Not filtering for just the `created` users in the past run period. It looks like MixPanel has removed the `$created` people property as it is not available in the API at the time of writing. See the comment in the `get_new_users` function.

2. Locally running `dev_appserver.py` will not allow you to run the job without mocking the KMS/GCS calls. I am sure you could open up the ACLs/settings a bit further but this is unexplored at this time.

3. All users are attempted to be loaded into the MailChimp list. The MailChimp API throws a 400 with the `mailchimp3` library used in the way that it is (maybe there is a better way?). The current members could be pulled first to not make this call and receive the error. Generically, all HTTP Errors are caught which is not ideal. This can certainly be improved.

4. There is no special logic for users with the same email address. The email is used as a key for the cleaned-up data.

## Pull Requests

Sure, but please give me some time.

## License

Apache 2.0.
