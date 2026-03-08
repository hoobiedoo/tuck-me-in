// AWS configuration — update these values from CDK outputs after deployment
// Run: cd backend && npx cdk deploy  — then copy the output values here

export const AWS_CONFIG = {
  region: "us-east-1",
  cognito: {
    userPoolId: "us-east-1_iQjWfBDww",
    userPoolClientId: "194sssm6666hkop3ibrsda6uf",
  },
  api: {
    baseUrl: "https://pswlwj90mi.execute-api.us-east-1.amazonaws.com/v1",
  },
  audioCdnBase: "https://d3sodr0o78ygpv.cloudfront.net",
};
