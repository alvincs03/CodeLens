import { fireEvent, render, screen } from '@testing-library/react';
import App from './App';

afterEach(() => {
  window.history.replaceState({}, '', '/');
});

test('renders the CodeLens title', () => {
  render(<App />);
  const titleElement = screen.getByRole('heading', { name: /CodeLens/i });
  expect(titleElement).toBeInTheDocument();
});

test('hides API key controls until GitHub is connected', () => {
  render(<App />);

  expect(screen.queryByRole('button', { name: /add api key/i })).not.toBeInTheDocument();
  expect(screen.getByText(/available after github is connected/i)).toBeInTheDocument();
});

test('opens, accepts input, and dismisses the API key panel', () => {
  window.history.replaceState({}, '', '/?token=test-token&login=test-user&avatar=test-avatar');
  render(<App />);

  fireEvent.click(screen.getByRole('button', { name: /add api key/i }));
  const keyInput = screen.getByPlaceholderText('sk-ant-...');
  fireEvent.change(keyInput, { target: { value: 'test-api-key' } });
  expect(keyInput).toHaveValue('test-api-key');

  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByPlaceholderText('sk-ant-...')).not.toBeInTheDocument();
});
