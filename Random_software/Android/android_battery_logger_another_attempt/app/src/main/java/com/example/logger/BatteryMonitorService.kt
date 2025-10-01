package com.example.logger

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class BatteryMonitorService : Service() {

    private val NOTIFICATION_CHANNEL_ID = "BatteryMonitorChannel"
    private val NOTIFICATION_ID = 101
    private lateinit var powerReceiver: BroadcastReceiver
    private lateinit var screenEventReceiver: BroadcastReceiver

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()

        // Receiver for charger events
        powerReceiver = object : BroadcastReceiver() { 
            override fun onReceive(context: Context?, intent: Intent?) {
                val ctx = context ?: return
                val loggerApp = application as? LoggerApplication ?: return

                val batteryPct = getBatteryPercentage(ctx)
                val timestamp = SimpleDateFormat("dd MMM yyyy 'at' HH:mm", Locale.getDefault()).format(Date())
                val message = when (intent?.action) {
                    Intent.ACTION_POWER_CONNECTED -> "Charger connected on $timestamp with battery at $batteryPct%"
                    Intent.ACTION_POWER_DISCONNECTED -> "Charger disconnected on $timestamp with battery at $batteryPct%"
                    else -> null
                }
                message?.let { loggerApp.addLogEntry(it) }
            }
        }
        val powerFilter = IntentFilter().apply {
            addAction(Intent.ACTION_POWER_CONNECTED)
            addAction(Intent.ACTION_POWER_DISCONNECTED)
        }
        registerReceiver(powerReceiver, powerFilter)

        // Receiver for screen lock/unlock events
        screenEventReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                val action = intent.action ?: return
                val loggerApp = context.applicationContext as? LoggerApplication ?: return

                val sdfDate = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
                val sdfDateTime = SimpleDateFormat("dd MMM yyyy 'at' HH:mm:ss", Locale.getDefault())
                val todayStr = sdfDate.format(Date())
                val nowStr = sdfDateTime.format(Date())
                val prefs = context.getSharedPreferences("screen_event_prefs", Context.MODE_PRIVATE)

                when (action) {
                    Intent.ACTION_USER_PRESENT -> {
                        val firstUnlockKey = "first_unlock_$todayStr"
                        if (!prefs.contains(firstUnlockKey)) {
                            val entry = "First unlock of the day: $nowStr"
                            prefs.edit().putBoolean(firstUnlockKey, true).apply()
                            loggerApp.addScreenEventLog(entry)
                        }
                    }
                    Intent.ACTION_SCREEN_OFF -> {
                        val lastLockKey = "last_lock_$todayStr"
                        val entry = "Last lock of the day: $nowStr"
                        val previousEntry = prefs.getString(lastLockKey, null)
                        previousEntry?.let { loggerApp.removeScreenEventLog(it) }
                        loggerApp.addScreenEventLog(entry)
                        prefs.edit().putString(lastLockKey, entry).apply()
                    }
                }
            }
        }
        val screenFilter = IntentFilter().apply {
            addAction(Intent.ACTION_USER_PRESENT)
            addAction(Intent.ACTION_SCREEN_OFF)
        }
        registerReceiver(screenEventReceiver, screenFilter)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notificationIntent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(this, 0, notificationIntent, PendingIntent.FLAG_IMMUTABLE)

        val notification = NotificationCompat.Builder(this, NOTIFICATION_CHANNEL_ID)
            .setContentTitle("Battery Monitor Running")
            .setContentText("Logging charger connection status in the background.")
            .setSmallIcon(android.R.drawable.ic_dialog_info) // Use a safe, standard system icon
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()

        startForeground(NOTIFICATION_ID, notification)
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(powerReceiver)
        unregisterReceiver(screenEventReceiver)
        stopForeground(true)
    }

    override fun onBind(intent: Intent?): IBinder? {
        return null
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val serviceChannel = NotificationChannel(
                NOTIFICATION_CHANNEL_ID,
                "Battery Monitor Service Channel",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(serviceChannel)
        }
    }

    private fun getBatteryPercentage(context: Context): Int {
        val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        return batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
    }
}