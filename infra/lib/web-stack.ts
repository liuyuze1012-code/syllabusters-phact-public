// Amplify Hosting app for frontend/ (connected to the GitHub repo), with the Cognito ids as env vars.
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface WebStackProps extends cdk.StackProps { userPoolId: string; userPoolClientId: string }

export class WebStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: WebStackProps) {
    super(scope, id, props);
    // TODO: CfnApp + CfnBranch (main), build spec for Vite, env VITE_USER_POOL_ID / VITE_USER_POOL_CLIENT_ID / VITE_API_URL
  }
}
