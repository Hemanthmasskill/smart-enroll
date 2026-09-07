import { useEffect, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { getNotifications, markNotificationRead, markAllNotificationsRead } from "../../services/api";
import PageHeader from "../../components/PageHeader";
import NotificationItem from "../../components/NotificationItem";
import "./Notifications.css";

export default function Notifications() {
  const { session } = useAuth();
  const [notifications, setNotifications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    getNotifications(session?.applicantId).then((data) => {
      setNotifications(data);
      setIsLoading(false);
    });
  }, [session]);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const handleMarkRead = async (notificationId) => {
    const updated = await markNotificationRead(session?.applicantId, notificationId);
    setNotifications(updated);
  };

  const handleMarkAllRead = async () => {
    const updated = await markAllNotificationsRead(session?.applicantId);
    setNotifications(updated);
  };

  if (isLoading) return <p>Loading notifications...</p>;

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

      {notifications.length === 0 ? (
        <div className="card notifications-empty">
          <p>You have no notifications yet.</p>
        </div>
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
