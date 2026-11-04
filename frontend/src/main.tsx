// Entry point: mounts <App/> with React Query and (later) Amplify Auth configured.
import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';

// TODO: Amplify.configure({ Auth: { Cognito: { userPoolId, userPoolClientId } } }) from import.meta.env
const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}><App /></QueryClientProvider>
  </React.StrictMode>
);
