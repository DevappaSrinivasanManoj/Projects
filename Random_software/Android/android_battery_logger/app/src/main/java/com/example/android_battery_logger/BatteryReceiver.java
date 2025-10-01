

package com.example.android_battery_logger;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.BatteryManager;
import android.os.Environment;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public class BatteryReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (action != null) {
            if (action.equals(Intent.ACTION_POWER_CONNECTED)) {
                logChargerEvent("Charger plugged in", context);
            } else if (action.equals(Intent.ACTION_POWER_DISCONNECTED)) {
                logChargerEvent("Charger plugged out", context);
            }
        }
    }

    private void logChargerEvent(String event, Context context) {
        int batteryLevel = getBatteryPercentage(context);
        String timeStamp = new SimpleDateFormat("dd MMM yyyy HH:mm", Locale.getDefault()).format(new Date());
        String logMessage = event + " at " + timeStamp + ", percentage when " + (event.contains("in") ? "plugged in" : "plugged out") + " : " + batteryLevel + "%\n";
        writeLog(logMessage);
    }

    private int getBatteryPercentage(Context context) {
        BatteryManager bm = (BatteryManager) context.getSystemService(Context.BATTERY_SERVICE);
        return bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
    }

    private void writeLog(String logMessage) {
        try {
            File logFile = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS), "BatteryLogs/battery_log.txt");
            if (!logFile.getParentFile().exists()) {
                logFile.getParentFile().mkdirs();
            }
            FileWriter writer = new FileWriter(logFile, true);
            writer.append(logMessage);
            writer.flush();
            writer.close();
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}
