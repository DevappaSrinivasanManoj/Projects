package com.example.logger

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.widget.TextView
import androidx.activity.ComponentActivity
import java.util.Calendar
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat

class MainActivity : ComponentActivity(), SharedPreferences.OnSharedPreferenceChangeListener {
    private val REQUEST_IGNORE_BATTERY_OPTIMIZATIONS = 1001
    private val REQUEST_SCHEDULE_EXACT_ALARM = 1002
    private val REQUEST_POST_NOTIFICATIONS = 1003

    private lateinit var logTextView: TextView
    private lateinit var screenLogTextView: TextView
    private lateinit var showLogButton: android.widget.Button
    private lateinit var showScreenLogButton: android.widget.Button
    private lateinit var setTimeButton: android.widget.Button
    private lateinit var selectedTimeTextView: TextView
    private val logList = mutableListOf<String>()
    private val screenLogList = mutableListOf<String>()
    private val PREFS_NAME = "battery_logger_prefs"
    private val SCREEN_PREFS_NAME = "screen_event_prefs"
    private val LOG_KEY = "log_list"
    private val SCREEN_LOG_KEY = "screen_log_list"
    private val TIME_KEY = "log_time"

    private var logVisible = false

    private val requestNotificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { isGranted: Boolean ->
            if (isGranted) {
                // Permission is granted, start the service
                startBatteryMonitorService()
            }
        }

    private fun getBatteryPercentage(context: Context): Int {
        // Use the modern and more reliable BatteryManager
        val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        return batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
    }

    private fun getCurrentTimestamp(): String {
        val now = java.util.Calendar.getInstance()
        val day = now.get(java.util.Calendar.DAY_OF_MONTH)
        val month = now.getDisplayName(java.util.Calendar.MONTH, java.util.Calendar.SHORT, java.util.Locale.getDefault())
        val year = now.get(java.util.Calendar.YEAR)
        val hour = String.format("%02d", now.get(java.util.Calendar.HOUR_OF_DAY))
        val minute = String.format("%02d", now.get(java.util.Calendar.MINUTE))
        return "$day $month $year at $hour:$minute"
    }

    private fun saveLog() {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(LOG_KEY, logList.joinToString("\n")).apply()
    }

    private fun loadLog() {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val saved = prefs.getString(LOG_KEY, null)
        if (!saved.isNullOrEmpty()) {
            logList.clear()
            logList.addAll(saved.split("\n"))
        }
    }

    private fun loadScreenLog() {
        val prefs = getSharedPreferences(SCREEN_PREFS_NAME, Context.MODE_PRIVATE)
        val saved = prefs.getString(SCREEN_LOG_KEY, null)
        if (!saved.isNullOrEmpty()) {
            screenLogList.clear()
            screenLogList.addAll(saved.split("\n"))
        }
    }

    private fun saveTime(hour: Int, minute: Int) {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(TIME_KEY, String.format("%02d:%02d", hour, minute)).apply()
        (application as? LoggerApplication)?.rescheduleDailyLog()
    }

    private fun loadTime(): String? {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(TIME_KEY, null)
    }

    private fun addLogEntry(entry: String) {
        logList.add(entry)
        if (logVisible) {
            logTextView.text = logList.joinToString("\n")
        }
        saveLog()
    }

    private fun startBatteryMonitorService() {
        val serviceIntent = Intent(this, BatteryMonitorService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Load existing logs first to prevent them from being overwritten.
        loadLog()
        loadScreenLog()

        // Ask user to disable battery optimization
        val pm = getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
        val packageName = packageName
        if (!pm.isIgnoringBatteryOptimizations(packageName)) {
            val intent = android.content.Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            intent.data = android.net.Uri.parse("package:$packageName")
            startActivityForResult(intent, REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
        }

        // Ask user to grant exact alarm permission on Android 12+
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.S) {
            val alarmManager = getSystemService(Context.ALARM_SERVICE) as android.app.AlarmManager
            if (!alarmManager.canScheduleExactAlarms()) {
                val intent = android.content.Intent(android.provider.Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM)
                startActivityForResult(intent, REQUEST_SCHEDULE_EXACT_ALARM)
            }
        }

        // Ask for notification permission on Android 13+ to start the foreground service
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
                // Permission is already granted, start the service
                startBatteryMonitorService()
            } else {
                // Request the permission
                requestNotificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        } else {
            // On older versions, no permission is needed, start the service directly
            startBatteryMonitorService()
        }

        // Layout
        val layout = android.widget.LinearLayout(this)
        layout.orientation = android.widget.LinearLayout.VERTICAL
        layout.setPadding(16, 16, 16, 16)

        setTimeButton = android.widget.Button(this)
        setTimeButton.text = "Set Daily Log Time"
        layout.addView(setTimeButton)

        selectedTimeTextView = TextView(this)
        selectedTimeTextView.text = "No time set"
        layout.addView(selectedTimeTextView)

        showLogButton = android.widget.Button(this)
        showLogButton.text = "Show Log"
        layout.addView(showLogButton)

        showScreenLogButton = android.widget.Button(this)
        showScreenLogButton.text = "Show Screen Log"
        layout.addView(showScreenLogButton)

        val shareLogsButton = android.widget.Button(this)
        shareLogsButton.text = "Share All Logs"
        layout.addView(shareLogsButton)

        val clearLogsButton = android.widget.Button(this)
        clearLogsButton.text = "Clear All Logs"
        layout.addView(clearLogsButton)

        logTextView = TextView(this)
        logTextView.setTextIsSelectable(true)
        logTextView.visibility = android.view.View.GONE
        layout.addView(logTextView)

        screenLogTextView = TextView(this)
        screenLogTextView.setTextIsSelectable(true)
        screenLogTextView.visibility = android.view.View.GONE
        layout.addView(screenLogTextView)

        setContentView(layout)

        val savedTime = loadTime()
        if (savedTime != null) {
            selectedTimeTextView.text = "Daily log time: $savedTime"
        }

        showLogButton.setOnClickListener {
            logVisible = !logVisible
            if (logVisible) {
                logTextView.text = logList.joinToString("\n")
                logTextView.visibility = android.view.View.VISIBLE
                screenLogTextView.visibility = android.view.View.GONE // Hide other log
                showLogButton.text = "Hide Log"
            } else {
                logTextView.visibility = android.view.View.GONE
                showLogButton.text = "Show Log"
            }
        }

        showScreenLogButton.setOnClickListener {
            // This is a simple toggle, assumes only one log can be visible at a time.
            val screenLogVisible = screenLogTextView.visibility == android.view.View.GONE
            if (screenLogVisible) {
                screenLogTextView.text = screenLogList.joinToString("\n")
                screenLogTextView.visibility = android.view.View.VISIBLE
                logTextView.visibility = android.view.View.GONE // Hide other log
                showScreenLogButton.text = "Hide Screen Log"
            } else {
                screenLogTextView.visibility = android.view.View.GONE
                showScreenLogButton.text = "Show Screen Log"
            }
        }

        shareLogsButton.setOnClickListener {
            val batteryLogs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getString(LOG_KEY, "No battery logs found.") ?: "No battery logs found."
            val screenLogs = getSharedPreferences(SCREEN_PREFS_NAME, Context.MODE_PRIVATE)
                .getString(SCREEN_LOG_KEY, "No screen logs found.") ?: "No screen logs found."

            val combinedLogs = """
                --- BATTERY & CHARGER LOGS ---
                $batteryLogs

                --- SCREEN LOCK/UNLOCK LOGS ---
                $screenLogs
            """.trimIndent()

            val sendIntent: Intent = Intent().apply {
                action = Intent.ACTION_SEND
                putExtra(Intent.EXTRA_TEXT, combinedLogs)
                type = "text/plain"
            }

            val shareIntent = Intent.createChooser(sendIntent, "Share Logs Via")
            startActivity(shareIntent)
        }

        clearLogsButton.setOnClickListener {
            // Show a confirmation dialog to prevent accidental deletion
            android.app.AlertDialog.Builder(this)
                .setTitle("Confirm Clear")
                .setMessage("Are you sure you want to clear all logs? This action cannot be undone.")
                .setPositiveButton("Clear") { _, _ ->
                    // User confirmed, proceed with clearing logs

                    // Clear battery logs, but preserve the scheduled time
                    val batteryPrefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                    batteryPrefs.edit().remove(LOG_KEY).apply()

                    // Clear all screen event logs and their daily markers
                    val screenPrefs = getSharedPreferences(SCREEN_PREFS_NAME, Context.MODE_PRIVATE)
                    screenPrefs.edit().clear().apply()

                    // Clear the in-memory lists and update the UI
                    logList.clear()
                    screenLogList.clear()
                    logTextView.text = ""
                    screenLogTextView.text = ""
                    android.widget.Toast.makeText(this, "All logs cleared.", android.widget.Toast.LENGTH_SHORT).show()
                }
                .setNegativeButton("Cancel", null)
                .show()
        }

        setTimeButton.setOnClickListener {
            val cal = java.util.Calendar.getInstance()
            val hour = cal.get(java.util.Calendar.HOUR_OF_DAY)
            val minute = cal.get(java.util.Calendar.MINUTE)
            val dialog = android.app.TimePickerDialog(this, { _, h, m ->
                saveTime(h, m)
                selectedTimeTextView.text = "Daily log time: %02d:%02d".format(h, m)
            }, hour, minute, true)
            dialog.show()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: android.content.Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_IGNORE_BATTERY_OPTIMIZATIONS) {
            // Optionally log the result or update UI if needed
        } else if (requestCode == REQUEST_SCHEDULE_EXACT_ALARM) {
            // After the user returns from the settings screen, reschedule the log.
            (application as? LoggerApplication)?.rescheduleDailyLog()
        }
    }

    override fun onResume() {
        super.onResume()
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).registerOnSharedPreferenceChangeListener(this)
        getSharedPreferences(SCREEN_PREFS_NAME, Context.MODE_PRIVATE).registerOnSharedPreferenceChangeListener(this)
    }

    override fun onPause() {
        super.onPause()
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).unregisterOnSharedPreferenceChangeListener(this)
        getSharedPreferences(SCREEN_PREFS_NAME, Context.MODE_PRIVATE).unregisterOnSharedPreferenceChangeListener(this)
    }

    override fun onSharedPreferenceChanged(sharedPreferences: SharedPreferences?, key: String?) {
        if (key == LOG_KEY) {
            // The battery log was updated, reload and update the UI
            runOnUiThread {
                loadLog()
                if (logVisible) {
                    logTextView.text = logList.joinToString("\n")
                }
            }
        } else if (key == SCREEN_LOG_KEY) {
            // The screen log was updated, reload and update the UI
            runOnUiThread {
                loadScreenLog()
                if (screenLogTextView.visibility == android.view.View.VISIBLE) {
                    screenLogTextView.text = screenLogList.joinToString("\n")
                }
            }
        }
    }
}
