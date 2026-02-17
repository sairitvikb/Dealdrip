const nodemailer = require('nodemailer');
require('dotenv').config();

class NotificationService {
    constructor() {
        // Email Configuration (Gmail SMTP)
        this.emailTransporter = nodemailer.createTransport({
            service: 'gmail',
            auth: {
                user: process.env.EMAIL_USER,
                pass: process.env.EMAIL_APP_PASSWORD // Gmail App Password
            }
        });
        
        console.log('📧 Email-only notification service initialized');
    }

    // Email-only notification system (Telegram removed)

    // Send Email Notification
    async sendEmailNotification(subject, message, toEmail) {
        if (!process.env.EMAIL_USER) {
            console.log('❌ Email not configured');
            return false;
        }

        const mailOptions = {
            from: process.env.EMAIL_USER,
            to: toEmail || process.env.DEFAULT_EMAIL_RECIPIENT,
            subject: subject,
            html: `
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; text-align: center;">
                        <h1 style="color: white; margin: 0;">🔥 DealDrip Alert</h1>
                    </div>
                    <div style="padding: 20px; background: #f9f9f9;">
                        <h2 style="color: #333;">${subject}</h2>
                        <div style="background: white; padding: 15px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
                            ${message.replace(/\n/g, '<br>')}
                        </div>
                        <p style="text-align: center; color: #666; margin-top: 20px;">
                            <em>Sent by DealDrip Notification System</em>
                        </p>
                    </div>
                </div>
            `
        };

        try {
            await this.emailTransporter.sendMail(mailOptions);
            console.log('✅ Email sent successfully');
            return true;
        } catch (error) {
            console.error('❌ Email error:', error.message);
            return false;
        }
    }

    // Send Email Notifications (Simplified)
    async sendUserNotification(title, message, userEmail = null, userPhone = null, notificationType = 'email') {
        console.log(`📧 Sending email notification to: ${userEmail || 'default recipient'}`);
        
        const targetEmail = userEmail || process.env.DEFAULT_EMAIL_RECIPIENT;
        
        // Send email notification
        try {
            const emailSuccess = await this.sendEmailNotification(title, message, targetEmail);
            console.log(`📊 Result: Email to ${targetEmail}: ${emailSuccess ? '✅' : '❌'}`);
            
            return {
                email: emailSuccess,
                success: emailSuccess
            };
        } catch (error) {
            console.error('❌ Email notification failed:', error.message);
            return {
                email: false,
                success: false
            };
        }
    }
    
    // Send Email Notification (Legacy - for testing)
    async sendNotification(title, message, emailRecipient = null) {
        console.log(`📧 Sending email notification: ${title}`);
        
        try {
            const emailSuccess = await this.sendEmailNotification(title, message, emailRecipient);
            
            console.log(`📊 Result: Email: ${emailSuccess ? '✅' : '❌'}`);
            
            return {
                email: emailSuccess,
                success: emailSuccess
            };
        } catch (error) {
            console.error('❌ Email notification error:', error.message);
            return {
                email: false,
                success: false
            };
        }
    }

    // Test Email Notifications
    async testNotifications() {
        console.log('🧪 Testing email notification system...\n');
        
        const testMessage = `This is a test email notification from DealDrip!\n\nTimestamp: ${new Date().toLocaleString()}`;
        
        return await this.sendNotification('Test Email Notification', testMessage);
    }
}

// Example usage
async function main() {
    const notifier = new NotificationService();
    
    // Test the email notification system
    await notifier.testNotifications();
    
    // Example deal notification (email-only)
    // await notifier.sendNotification(
    //     'New Deal Alert!',
    //     'MacBook Pro 16" - 50% OFF\nOriginal Price: $2,499\nSale Price: $1,249\nSavings: $1,250\n\nLink: https://example.com/deal',
    //     'user@example.com'
    // );
}

// Export for use in other files
module.exports = NotificationService;

// Run if called directly
if (require.main === module) {
    main().catch(console.error);
}