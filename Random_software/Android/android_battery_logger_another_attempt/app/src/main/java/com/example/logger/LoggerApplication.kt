package com.example.logger

import android.app.Application
import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import java.util.Calendar

class LoggerApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        // This is a better place to schedule the alarm, as it runs once when the app starts.
        rescheduleDailyLog()
    }

    @Synchronized
    fun addLogEntry(entry: String) {
        val prefs = getSharedPreferences("battery_logger_prefs", Context.MODE_PRIVATE)
        val currentLogs = prefs.getString("log_list", "")

        val updatedLogs = if (currentLogs.isNullOrEmpty()) {
            entry
        } else {
            // Prepend new logs so they appear at the top
            "$entry\n$currentLogs"
        }

        prefs.edit().putString("log_list", updatedLogs).apply()
    }

    @Synchronized
    fun addScreenEventLog(entry: String) {
        val prefs = getSharedPreferences("screen_event_prefs", Context.MODE_PRIVATE)
        val currentLogs = prefs.getString("screen_log_list", "")
        val updatedLogs = if (currentLogs.isNullOrEmpty()) {
            entry
        } else {
            "$entry\n$currentLogs"
        }
        prefs.edit().putString("screen_log_list", updatedLogs).apply()
    }

    @Synchronized
    fun removeScreenEventLog(entry: String) {
        val prefs = getSharedPreferences("screen_event_prefs", Context.MODE_PRIVATE)
        val currentLogs = prefs.getString("screen_log_list", "")?.split('\n')?.toMutableList()

        if (currentLogs != null) {
            currentLogs.remove(entry)
            val updatedLogs = currentLogs.joinToString("\n")
            prefs.edit().putString("screen_log_list", updatedLogs).apply()
        }
    }


    fun rescheduleDailyLog() {
        val prefs = getSharedPreferences("battery_logger_prefs", Context.MODE_PRIVATE)
        val savedTime = prefs.getString("log_time", null)

        savedTime?.split(":")?.let { parts ->
            if (parts.size == 2) {
                val hour = parts[0].toIntOrNull() ?: return
                val minute = parts[1].toIntOrNull() ?: return

                val alarmManager = getSystemService(Context.ALARM_SERVICE) as AlarmManager
                val intent = Intent(this, DailyLogReceiver::class.java)
                val pendingIntent = PendingIntent.getBroadcast(this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                val calendar = Calendar.getInstance().apply {
                    set(Calendar.HOUR_OF_DAY, hour)
                    set(Calendar.MINUTE, minute)
                    set(Calendar.SECOND, 0)
                    set(Calendar.MILLISECOND, 0)
                    if (timeInMillis <= System.currentTimeMillis()) {
                        add(Calendar.DAY_OF_MONTH, 1)
                    }
                }
                // Use setExactAndAllowWhileIdle for precision, especially on newer Android versions.
                // This requires the SCHEDULE_EXACT_ALARM permission in the manifest.
                if (alarmManager.canScheduleExactAlarms()) {
                    alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, calendar.timeInMillis, pendingIntent)
                }
                // Note: Since this is not a repeating alarm, the receiver will need to reschedule the next one.
            }
        }
    }
}