<#
.SYNOPSIS
    One-time bootstrap of the Moving CRM stack.

.DESCRIPTION
    Creates the CloudFormation stack with:
    - VPC + subnets
    - RDS PostgreSQL (managed password via Secrets Manager)
    - S3 bucket for frontend
    - CodePipeline + CodeBuild (auto-deploys on git push)
    - SSM parameters for DB config
    - CloudFormation execution role for self-mutating pipeline

    Lambda resources are deployed by the pipeline on the first git push
    (DeployLambda=false during bootstrap, pipeline sets it to true).

.NOTES
    Prerequisites:
    1. AWS CLI configured (aws configure)
    2. A CodeStar Connection to GitHub - create one at:
       https://console.aws.amazon.com/codesuite/settings/connections
       Then paste the ARN below.
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubConnectionArn,

    [string]$Environment = "dev",
    [string]$GitHubRepo = "nechama-she/moving-crm",
    [string]$GitHubBranch = "main",
    [string]$AllowedCIDR = "0.0.0.0/0"
)

$StackName = "moving-crm-$Environment"

Write-Host "Bootstrapping stack: $StackName" -ForegroundColor Cyan
Write-Host "This will create: VPC, RDS PostgreSQL, S3, CodePipeline, CodeBuild" -ForegroundColor Yellow
Write-Host "Lambda resources will be created by the pipeline on the first git push." -ForegroundColor Yellow
Write-Host ""

aws cloudformation deploy `
    --template-file infra/template.yaml `
    --stack-name $StackName `
    --capabilities CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        "Environment=$Environment" `
        "GitHubConnectionArn=$GitHubConnectionArn" `
        "GitHubRepo=$GitHubRepo" `
        "GitHubBranch=$GitHubBranch" `
        "AllowedCIDR=$AllowedCIDR" `
        "DeployLambda=false"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Stack deployed successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Outputs:" -ForegroundColor Cyan
    aws cloudformation describe-stacks `
        --stack-name $StackName `
        --query "Stacks[0].Outputs" `
        --output table
} else {
    Write-Host "Deployment failed. Check CloudFormation console for details." -ForegroundColor Red
}
