#!/usr/bin/env python

from git import Repo
from boto3 import session
from shutil import rmtree
import os
import zipfile
import logging
import json

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
        self._name = name
        self._codecommit_arn = codecommit_arn
        self.codecommit = self.session.client('codecommit', region_name=region)
        self._zip_filename = None
        self._s3_bucket = None
        self._s3_key = None
        self._lambda_config = None
        self._local_lambda_path = None
        self._function_name = None

    def git_clone(self, repository):
        try:
            response = self.codecommit.get_repository(repositoryName=repository)
            # clone_url = response['repositoryMetadata']['cloneUrlHttp']
            clone_ssh = response['repositoryMetadata']['cloneUrlSsh']
            destination = root_dir + "/" + repository
            if os.path.exists(destination):
                self.git_pull(repository)
            Repo.clone_from(clone_ssh, destination)
            return clone_ssh
        except Exception as e:
            print(e)
            print(
                'Error getting repository {}. Make sure it exists and that your \
                repository is in the same region as this function.'.format(
                    repository))
            raise e

    def configure_lambda_function(self, repository):
        try:
            self.configure_lambda_function_from_config_json(repository)
            self._s3_bucket = self._lambda_config.S3Bucket
            self._local_lambda_path = self._lambda_config.LambdaDirectory
            self._function_name = self._lambda_config.FunctionName
        except Exception as e:
            print (e.message)
            print("Failed to configure Lambda function from config file")
            raise e

    def configure_lambda_function_from_config_json(self, repository, config_file_name='config.json'):
        config_json_path = root_dir + "/" + repository + "/" + config_file_name
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

    def zip_package(self, repository, lambda_directory='src/python/'):
        try:
            path = root_dir + "/" + repository
            self._zip_filename = repository + '.zip'
            ziph = zipfile.ZipFile(root_dir + '/' + self._zip_filename, 'w', zipfile.ZIP_DEFLATED)
            exclude = {'.git'}

            # ziph is zipfile handle
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in exclude]
                for f in files:
                    lambda_path = path + "/" + lambda_directory.strip('/')
                    lambda_path_inside_zip = root.replace(lambda_path, repository) + "/"
                    ziph.write(os.path.join(root, f), lambda_path_inside_zip + f)
        except Exception as e:
            print (e.message)
            raise e

    def upload_zip_file_to_s3(self, bucket):
        s3_client = self.session.client('s3')
        self._s3_bucket = bucket
        try:
            logger.info("Uploading %s to S3..." % (self._zip_filename))
            self._s3_key = "deployments/" + self._zip_filename
            s3_client.upload_file(root_dir + "/" + self._zip_filename, self._s3_bucket, self._s3_key)
        except Exception as e:
            print(e.message)
            raise e

    def update_lambda_function_code(self, function_name, s3_key=None):
        lambda_client = self.session.client('lambda')

        if s3_key is None:
            s3_key = self._s3_key

        # prefix, filename = s3_key.split("/", 1)
        parameters = {
            'FunctionName': function_name,
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

    def rm_local_repo(self, repository):
        try:
            rmtree(root_dir + "/" + repository)
            return True
        except Exception as e:
            print (e.message)
            raise e

    def git_pull(self, repository):
        # To do: git pull, not rm the local repo
        self.rm_local_repo(repository)


def lambda_handler(event, context):
    if 'Credentials' in event.keys():
        aws_access_key_id = event['Credentials']['aws_access_key_id']
        aws_secret_access_key = event['Credentials']['aws_secret_access_key']
    else:
        aws_access_key_id = None
        aws_secret_access_key = None

    function_arn = event['Records'][0]['eventSourceARN']
    arn, provider, service, region, akid, resource_id = function_arn.split(":")
    deployment = Deployment("test", region, function_arn,
                            aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)
    references = {reference['ref'] for reference in event['Records'][0]['codecommit']['references']}
    # print("References: " + str(references))

    # Get the repository from the event and show its git clone URL
    repository = event['Records'][0]['eventSourceARN'].split(':')[5]
    deployment.git_clone(repository)
    deployment.configure_lambda_function_from_config_json(repository)
    deployment.zip_package(repository)
    deployment.upload_zip_file_to_s3("curalate-lambda-qa")
    deployment.update_lambda_function_code("test_function")
    return True



class Event:
    def __init__(self, **entries):
        self.__dict__.update(entries)


class Context:
    def __init__(self, **entries):
        self.__dict__.update(entries)

if __name__ == "__main__":

    credentials = dict([
        ('aws_access_key_id', cundo_aws_access_key_id),
        ('aws_secret_access_key', cundo_aws_secret_access_key)
    ])
    event = dict([(
        "Records",[
            dict([
                ('eventSourceARN', "arn:aws:codecommit:us-east-1:176853725791:tagger-asg"),
                ('codecommit', dict([
                    ('references', [dict([('ref', 'ref_1')])])
                ]))
            ])
        ]),
        ('Credentials', credentials)
    ])
    context = dict([("invoked_function_arn", "arn:aws:lambda:us-east-1:176853725791:function:cundo-lambda")])

    lambda_handler(event, Context(**context))
