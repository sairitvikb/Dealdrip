// Email-only notification sender for Python to call
const NotificationService = require('./notifications');

async function main() {
    const args = process.argv.slice(2);
    
    if (args.length < 3) {
        console.log('Usage: node send_notification.js "title" "message" "product_url" [userEmail] [userPhone] [notificationType]');
        process.exit(1);
    }
    
    const [title, message, productUrl, userEmail = null, userPhone = null, notificationType = 'email'] = args;
    
    const notifier = new NotificationService();
    
    try {
        // Use the email-only notification method
        const result = await notifier.sendUserNotification(title, message, userEmail, userPhone, notificationType);
        
        if (result.success) {
            console.log('✅ NOTIFICATION_SUCCESS');
            console.log(`Email: ${result.email ? '✅' : '❌'}`);
            console.log(`Target User: ${userEmail || 'Default recipient'}`);
            console.log('📧 Email-only system - simple and reliable');
        } else {
            console.log('❌ NOTIFICATION_FAILED');
        }
    } catch (error) {
        console.log('❌ NOTIFICATION_ERROR:', error.message);
    }
}

main();
