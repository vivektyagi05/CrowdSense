import { Link } from 'react-router-dom';

/**
 * One button for the whole app. variant: primary | secondary | ghost | danger. size: md | sm.
 * Pass `to` to render a router Link styled as a button (navigation), otherwise a real <button> (action).
 */
export default function Button({ variant = 'primary', size = 'md', to, type = 'button', loading = false, className = '', children, ...rest }) {
  const cls = `btn btn--${variant} btn--${size} ${className}`.trim();
  if (to) return <Link to={to} className={cls} {...rest}>{children}</Link>;
  return (
    <button type={type} className={cls} aria-busy={loading || undefined} disabled={rest.disabled || loading} {...rest}>
      {children}
    </button>
  );
}
