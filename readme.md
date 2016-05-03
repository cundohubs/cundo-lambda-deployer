Lambda function that is triggered on git pushes to CodeCommit and updates a Lambda Function

Requirements
Lambda function pre-created (To do: add Lambda creation option)
config.json in top level that defines how Lambda function is updated:
{'S3Bucket': <s3 bucket where zip packages will be shipped/stored>,
 'LambdaDirectory': <path of Lambda function code in relation to top root directory>,
 'FunctionName': <Name of Lambda function>
}
