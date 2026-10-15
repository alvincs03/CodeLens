import { render, screen } from '@testing-library/react';
import App from './App';

test('renders the CodeLens title', () => {
  render(<App />);
  const titleElement = screen.getByRole('heading', { name: /CodeLens/i });
  expect(titleElement).toBeInTheDocument();
});
