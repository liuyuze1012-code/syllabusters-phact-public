// Cognito user pool: no self sign-up, custom:school_id, groups faculty / school-admin / aspph-reviewer.
// ASPPH staff are covered by the aspph-reviewer group; there is no separate IT role.
import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import { Construct } from 'constructs';

export class AuthStack extends cdk.Stack {
  readonly userPool: cognito.UserPool;
  readonly userPoolId: string;
  readonly userPoolClientId: string;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    this.userPool = new cognito.UserPool(this, 'Users', {
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      customAttributes: { school_id: new cognito.StringAttribute({ mutable: false }) },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    for (const g of ['faculty', 'school-admin', 'aspph-reviewer']) {
      new cognito.CfnUserPoolGroup(this, `Group-${g}`, { userPoolId: this.userPool.userPoolId, groupName: g });
    }
    const client = this.userPool.addClient('WebClient', { authFlows: { userSrp: true } });
    this.userPoolId = this.userPool.userPoolId;
    this.userPoolClientId = client.userPoolClientId;
    // Demo users are created by scripts/seed_users.py, not here.
  }
}
