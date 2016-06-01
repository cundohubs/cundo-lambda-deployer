#!/usr/bin/env python

from git import Repo
from boto3 import session
from shutil import rmtree
import os
import zipfile
import logging
import json
import argparse
import ConfigParser

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)
root_dir = "/tmp"


class DeploymentConfig:
    def __init__(self, **config_json):
        self.__dict__.update(config_json)


class Deployment:
    def __init__(self, name, region, codecommit_arn, aws_access_key_id=None, aws_secret_access_key=None):
        self.session = session.Session(aws_access_key_id=aws_access_key_id,
                                       aws_secret_access_key=aws_secret_access_key,
                                       region_name=region)
        self._repository_name = name
        self._codecommit_arn = codecommit_arn
        self.codecommit = self.session.client('codecommit', region_name=region)
        self.repository_name = self._codecommit_arn.split(":")[-1]
        self.local_repo_path = root_dir + "/" + self.repository_name + "/"
        self._zip_filename = None
        self._s3_bucket = None
        self._s3_key = None
        self._s3_prefix = None
        self._lambda_config = None
        self._local_lambda_path_inside_repo = None
        self._function_name = None

    def get_deployment_configurations(self, config_file_name='lambda-deploy.json'):
        config_file = self.local_repo_path + config_file_name
        with open(config_file) as data_file:
            data = json.load(data_file)
        configurations = data["DeploymentConfiguration"]
        self._s3_prefix = configurations["S3PrefixDeployments"]
        self._local_lambda_path_inside_repo = configurations["LambdaDirectory"]
        self._s3_bucket = configurations["S3Bucket"]

    def git_clone(self):
        try:
            response = self.codecommit.get_repository(repositoryName=self._repository_name)
            # clone_url = response['repositoryMetadata']['cloneUrlHttp']
            clone_ssh = response['repositoryMetadata']['cloneUrlSsh']
            destination = self.local_repo_path
            if os.path.exists(destination):
                self.git_pull(self._repository_name)
            Repo.clone_from(clone_ssh, destination)
            return clone_ssh
        except Exception as e:
            print(e)
            print(
                'Error getting repository {}. Make sure it exists and that your \
                repository is in the same region as this function.'.format(
                    self._repository_name))
            raise e

    def configure_lambda_function_deprecated(self, repository):
        try:
            self.configure_lambda_function_from_config_json(repository)
            self._s3_bucket = self._lambda_config.S3Bucket
            self._local_lambda_path_inside_repo = self._lambda_config.LambdaDirectory
            self._function_name = self._lambda_config.FunctionName
        except Exception as e:
            print (e.message)
            print("Failed to configure Lambda function from config file")
            raise e

    def configure_lambda_function_from_config_json(self, config_file_name='config.json'):
        config_json_path = self.repository_name + config_file_name
        try:
            with open(config_json_path) as data_file:
                data = json.load(data_file)
            self._lambda_config = DeploymentConfig(**data)
            data_file.close()
        except Exception as e:
            print(e.message)
            print("Failed to load configurations from file %s" % config_json_path)
            # raise e
            data = {'S3Bucket': 'curalate-lambda-qa',
                    'LambdaDirectory': 'src/python/',
                    'FunctionName': 'test_function'}
            self._lambda_config = DeploymentConfig(**data)

    def zip_package(self):
        lambda_directory = self._local_lambda_path_inside_repo
        try:
            lambda_path = self.local_repo_path + "/" + lambda_directory.strip('/')
            self._zip_filename = self._repository_name + '.zip'
            ziph = zipfile.ZipFile(root_dir + '/' + self._zip_filename, 'w', zipfile.ZIP_DEFLATED)
            exclude = {'.git'}

            # ziph is zipfile handle
            for root, dirs, files in os.walk(lambda_path):
                dirs[:] = [d for d in dirs if d not in exclude]
                for f in files:
                    lambda_path_inside_zip = root.replace(lambda_path, self._repository_name) + "/"
                    ziph.write(os.path.join(root, f), lambda_path_inside_zip + f)
        except Exception as e:
            print (e.message)
            raise e

    def upload_zip_file_to_s3(self, bucket=None):
        s3_client = self.session.client('s3')
        if bucket is not None:
            self._s3_bucket = bucket
        try:
            logger.info("Uploading %s to S3..." % self._zip_filename)
            self._s3_key = self._s3_prefix + self._zip_filename
            s3_client.upload_file(root_dir + "/" + self._zip_filename, self._s3_bucket, self._s3_key)
        except Exception as e:
            print(e.message)
            raise e

    def get_s3_key_version(self, s3_key):
        self._s3_bucket = self._s3_bucket
        try:
            logger.info("Getting version id of %s from S3..." % (s3_key))
            s3_resource = self.session.resource('s3')
            obj = s3_resource.Object(self._s3_bucket, s3_key)
            return obj.version_id
        except Exception, e:
            print(e.message)
            raise e

    def load_lambda_configuration_from_file(self, file_name="lambda-deploy.json"):
        config_file = self.local_repo_path + file_name
        with open(config_file) as data_file:
            data = json.load(data_file)
        configurations = data["LambdaConfiguration"]
        configurations["Handler"] = self.repository_name + "/" + configurations["Handler"]
        # configurations["Code"]["S3ObjectVersion"] = self.get_s3_key_version(self._s3_key)
        del configurations["Code"]["S3Key"]
        del configurations["Code"]["S3Bucket"]
        del configurations["Code"]["S3ObjectVersion"]
        del configurations["VpcConfig"]
        return configurations

    def create_lambda_function(self):
        parameters = self.load_lambda_configuration_from_file()
        try:
            zipdata = file_get_contents(root_dir + "/" + self._zip_filename)
            lambda_client = self.session.client('lambda')
            parameters['Code']['ZipFile'] = zipdata
            lambda_client.create_function(**parameters)
        except Exception as e:
            print("Failed to create lambda function from %s/%s" % (self._s3_bucket, self._s3_key))
            print ("Parameters: %s" % parameters)
            print (e.message)
            raise e

    def update_lambda_function_code(self, s3_key=None):
        lambda_client = self.session.client('lambda')

        s3_key = self._s3_key if s3_key is None else s3_key

        # prefix, filename = s3_key.split("/", 1)
        parameters = {
            'FunctionName': self._function_name,
            'S3Bucket': self._s3_bucket,
            'S3Key': s3_key,
            'Publish': True
        }
        try:
            lambda_client.update_function_code(**parameters)
        except Exception as e:
            print("Failed to publish zip file %s to S3 Bucket %s" % (s3_key, self._s3_bucket))
            print (e.message)
            raise e

    def rm_local_repo(self):
        try:
            rmtree(self.local_repo_path)
            return True
        except Exception as e:
            print (e.message)
            raise e

    def git_pull(self):
        # To do: git pull, not rm the local repo
        self.rm_local_repo()


def file_get_contents(filename):
    with open(filename) as f:
        return f.read()


def lambda_handler(event, context):
    # Load credentials only if we are testing. Otherwise, use IAM Role
    event = json.loads(event)
    if 'Credentials' in event.keys():
        aws_access_key_id = event['Credentials']['aws_access_key_id']
        aws_secret_access_key = event['Credentials']['aws_secret_access_key']
    else:
        aws_access_key_id = None
        aws_secret_access_key = None

    function_arn = event['Records'][0]['eventSourceARN']
    arn, provider, service, region, akid, resource_id = function_arn.split(":")
    # references = {reference['ref'] for reference in event['Records'][0]['codecommit']['references']}
    # print("References: " + str(references))

    # Get the repository from the event and show its git clone URL
    repository = event['Records'][0]['eventSourceARN'].split(':')[5]
    deployment = Deployment(repository, region, function_arn,
                            aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)
    deployment.git_clone()
    deployment.get_deployment_configurations()
    # deployment.configure_lambda_function_from_config_json()
    deployment.zip_package()
    deployment.upload_zip_file_to_s3()
    # deployment.load_lambda_configuration_from_file()
    deployment.create_lambda_function()
    # deployment.update_lambda_function_code()
    output = event
    output['Status'] = "OK"
    return output


class Event:
    def __init__(self, **entries):
        self.__dict__.update(entries)


class Context:
    def __init__(self, **entries):
        self.__dict__.update(entries)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dryrun", help="Dry run - don't change anything in AWS")
    parser.add_argument("--account", help="AWS Account Name", default="QA")
    parser.add_argument("--secretkey", help="AWS Secret Key", default="deprecated")
    args = parser.parse_args()

    credentials = ConfigParser.ConfigParser()
    configs = ConfigParser.ConfigParser()

    home_dir = os.environ['HOME']
    credentials_file = home_dir + "/.aws/credentials"

    credentials.read(credentials_file)

    account_name = args.account
    aws_access_key_id = credentials.get(account_name, "aws_access_key_id")
    aws_secret_access_key = credentials.get(account_name, "aws_secret_access_key")
    aws_credentials = dict([
        ('aws_access_key_id', aws_access_key_id),
        ('aws_secret_access_key', aws_secret_access_key)])

    sample_arn = "arn:aws:lambda:us-east-1:123456789012:function:tagging-lambda"

    records = [dict([
                ('eventSourceARN', "arn:aws:codecommit:us-east-1:176853725791:tagger-asg"),
                ('codecommit', dict([
                    ('references', [dict([('ref', 'ref_1')])])
                ]))
            ])]
    event = dict([("invokingEvent",
                   dict([("configurationItem",
                         dict([("configuration",
                               dict([("instanceId", "i-deaed543")])
                              ),
                               ("configurationItemStatus", "OK")])
                          )])),
                  ("Records", records),
                  ("eventLeftScope", False),
                  ("Credentials", aws_credentials),
            ])
    context = dict([("invoked_function_arn", sample_arn),
                    ("keys", dict([
                        ("aws_access_key_id", aws_access_key_id),
                        ("aws_secret_access_key", aws_secret_access_key)]
                    ))
                  ])

    lambda_handler(json.dumps(event), Context(**context))
