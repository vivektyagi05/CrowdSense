import { usePageTitle } from '../lib/title.js';
import Button from '../ui/Button.jsx';
import { EmptyState } from '../ui/States.jsx';

export default function NotFoundPage() {
  usePageTitle('Page not found');
  return (
    <div className="container page">
      <EmptyState title="Page not found" action={<Button to="/">Plan a journey</Button>}>
        There is no page at this address. Check the link, or start from the journey planner.
      </EmptyState>
    </div>
  );
}
