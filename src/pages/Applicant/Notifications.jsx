import { useEffect, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { getNotifications, markNotificationRead, markAllNotificationsRead } from "../../services/api";
import PageHeader from "../../components/PageHeader";
import NotificationItem from "../../components/NotificationItem";
import { EmptyState, ErrorState, LoadingState } from "../../components/AsyncState";
import "./Notifications.css";

export default function Notifications() {
  const { session } = useAuth();
  const [notifications, setNotifications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");

  useEffect(() => {
    let mounted = true;
    getNotifications(session?.applicantId)
      .then((data) => {
        if (mounted) setNotifications(data);
      })
      .catch((loadError) => {
        if (mounted) setError(loadError.message || "Unable to load notifications.");
      })
      .finally(() => {
        if (mounted) setIsLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [session]);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const handleMarkRead = async (notificationId) => {
    const updated = await markNotificationRead(session?.applicantId, notificationId);
    setNotifications(updated);
    setFeedback("Notification marked as read. Dashboard unread count is synchronized.");
  };

  const handleMarkAllRead = async () => {
    const updated = await markAllNotificationsRead(session?.applicantId);
    setNotifications(updated);
    setFeedback("All notifications marked as read. Dashboard unread count is now synchronized.");
  };

  if (isLoading) return <LoadingState message="Loading notifications…" />;
  if (error) return <ErrorState message={error} />;

  return (
    <div>
      <PageHeader
        title="Notifications"
        subtitle={unreadCount > 0 ? `${unreadCount} unread notification${unreadCount === 1 ? "" : "s"}` : "You're all caught up."}
        actions={
          unreadCount > 0 && (
            <button className="btn btn-secondary" onClick={handleMarkAllRead}>
              Mark All as Read
            </button>
          )
        }
      />

      {feedback && (
        <div className="notification-feedback" role="status" aria-live="polite">
          {feedback}
        </div>
      )}

      {notifications.length === 0 ? (
        <EmptyState title="No notifications yet" message="Workflow updates will appear here." />
      ) : (
        <ul className="notifications-list">
          {notifications.map((notification) => (
            <NotificationItem
              key={notification.id}
              notification={notification}
              onMarkRead={() => handleMarkRead(notification.id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
