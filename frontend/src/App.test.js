import { render, screen } from '@testing-library/react';
import App from './App';

test('renders Code Review Buddy title', () => {
  render(<App />);
  const titleElement = screen.getByText(/Code Review Buddy/i);
  expect(titleElement).toBeInTheDocument();
});
