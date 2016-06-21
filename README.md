# lambda-deployer
Automated Lambda deployer that runs on AWS Lambda

# Purpose:
Initially written for AWS CodeCommit, this is a Python script built for AWS Lambda that is triggered by a commit to a CodeCommit repository.

# Flow:
1. Code is committed to a CodeCommit repository
2. Commit triggers Lambda function
3. Lambda function git clone/pulls recent changes
4. Based on path relative to the git repository root, create a zip file of that subdirectory
5. Upload zip file to S3
6. Create/update AWS Lambda function with the zip file + configurations


# To do:
1. Step 6 above actually depends on manual configuration set up first. That means there's some hard-coding. Need to remove the hard-coding at this point.
2. Design was to have a lambda-configuration.json at the root level of the git repo that defined the Lambda function configurations.
3. This code currently works off only the master branch but should include options for dev builds/branches, etc.
