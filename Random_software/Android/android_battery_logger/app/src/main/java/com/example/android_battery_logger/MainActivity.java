
package com.example.android_battery_logger;

import android.Manifest;
import android.app.TimePickerDialog;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Environment;
import android.view.View;
import android.widget.Button;
import android.widget.TimePicker;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import java.io.File;
import java.util.Calendar;
import java.util.concurrent.TimeUnit;

public class MainActivity extends AppCompatActivity {

    private static final int REQUEST_WRITE_STORAGE = 112;
    private Button pauseResumeButton;
    private TimePicker timePicker;
    private boolean isLoggingPaused = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        pauseResumeButton = findViewById(R.id.pauseResumeButton);
        timePicker = findViewById(R.id.timePicker);

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQUEST_WRITE_STORAGE);
        }

        pauseResumeButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (isLoggingPaused) {
                    resumeLogging();
                } else {
                    pauseLogging();
                }
            }
        });

        timePicker.setOnTimeChangedListener(new TimePicker.OnTimeChangedListener() {
            @Override
            public void onTimeChanged(TimePicker view, int hourOfDay, int minute) {
                scheduleDailyLog(hourOfDay, minute);
            }
        });
    }

    private void pauseLogging() {
        WorkManager.getInstance(this).cancelUniqueWork("daily_battery_log");
        isLoggingPaused = true;
        pauseResumeButton.setText("Resume Logging");
        Toast.makeText(this, "Logging Paused", Toast.LENGTH_SHORT).show();
    }

    private void resumeLogging() {
        isLoggingPaused = false;
        pauseResumeButton.setText("Pause Logging");
        int hour = timePicker.getHour();
        int minute = timePicker.getMinute();
        scheduleDailyLog(hour, minute);
        Toast.makeText(this, "Logging Resumed", Toast.LENGTH_SHORT).show();
    }

    private void scheduleDailyLog(int hour, int minute) {
        Calendar calendar = Calendar.getInstance();
        calendar.set(Calendar.HOUR_OF_DAY, hour);
        calendar.set(Calendar.MINUTE, minute);
        calendar.set(Calendar.SECOND, 0);

        if (calendar.before(Calendar.getInstance())) {
            calendar.add(Calendar.DAY_OF_MONTH, 1);
        }

        long initialDelay = calendar.getTimeInMillis() - System.currentTimeMillis();

        PeriodicWorkRequest dailyLogWorkRequest = new PeriodicWorkRequest.Builder(DailyLogger.class, 1, TimeUnit.DAYS)
                .setInitialDelay(initialDelay, TimeUnit.MILLISECONDS)
                .build();

        WorkManager.getInstance(this).enqueueUniquePeriodicWork("daily_battery_log", ExistingPeriodicWorkPolicy.REPLACE, dailyLogWorkRequest);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_WRITE_STORAGE) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                // Permission granted
            } else {
                Toast.makeText(this, "Permission denied. App cannot write logs.", Toast.LENGTH_LONG).show();
            }
        }
    }
}
