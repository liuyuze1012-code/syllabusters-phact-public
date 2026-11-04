// KMS key + the 4 S3 buckets (knowledge, uploads, exports, intake).
// Every bucket: KMS encryption, Block Public Access, HTTPS only. Least-privilege grants live in the stacks that use them.
import * as cdk from 'aws-cdk-lib';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export class FoundationStack extends cdk.Stack {
  readonly key: kms.Key;
  readonly knowledgeBucket: s3.Bucket;
  readonly uploadsBucket: s3.Bucket;
  readonly exportsBucket: s3.Bucket;
  readonly intakeBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    this.key = new kms.Key(this, 'PhactKey', { enableKeyRotation: true });
    const secure = (name: string, extra: Partial<s3.BucketProps> = {}) =>
      new s3.Bucket(this, name, {
        encryption: s3.BucketEncryption.KMS,
        encryptionKey: this.key,
        blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
        enforceSSL: true,
        removalPolicy: cdk.RemovalPolicy.DESTROY, // hackathon sandbox; change for production
        autoDeleteObjects: true,
        ...extra,
      });
    this.knowledgeBucket = secure('Knowledge', { versioned: true });   // kb/ (synced) + originals/ (not synced)
    this.uploadsBucket = secure('Uploads', { versioned: true });       // TODO: CORS for presigned PUT from the Amplify domain
    this.exportsBucket = secure('Exports', { lifecycleRules: [{ expiration: cdk.Duration.days(7) }] });
    this.intakeBucket = secure('Intake');                               // incoming/ staged/ approved/ rejected/ exemplar-candidates/
  }
}
