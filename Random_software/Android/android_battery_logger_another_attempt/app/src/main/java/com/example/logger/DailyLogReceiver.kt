package com.example.logger

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.BatteryManager
import java.util.Calendar

class DailyLogReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val loggerApp = context.applicationContext as? LoggerApplication ?: return

        val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val batteryPct = batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)

        val now = Calendar.getInstance()
        val day = now.get(Calendar.DAY_OF_MONTH)
        val month = now.getDisplayName(Calendar.MONTH, Calendar.SHORT, java.util.Locale.getDefault())
        val year = now.get(Calendar.YEAR)
        val hour = String.format("%02d", now.get(Calendar.HOUR_OF_DAY))
        val minute = String.format("%02d", now.get(Calendar.MINUTE))
        val entry = "Battery percentage on $day $month $year at $hour:$minute is : $batteryPct%"
        loggerApp.addLogEntry(entry)

        // Reschedule the alarm for the next day since we are using a one-time exact alarm.
        loggerApp.rescheduleDailyLog()
    }
}
