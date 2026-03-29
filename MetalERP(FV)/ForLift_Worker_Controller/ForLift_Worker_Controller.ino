#include <ArduinoJson.h>
#include <rpcWiFi.h>
#include <ArduinoHttpClient.h>
#include <TFT_eSPI.h>

TFT_eSPI tft = TFT_eSPI();


const char* ssid = "LUTES-2.4GHZ";
const char* password = "Lutesnorppa";


const char* server = "192.168.8.119";
int port = 8000;


const char* endpoint = "/api/delivery-statuses/";


const char* apiKey = "hNOzG2SI.w6KC5oY9V4RECZMOyI2zJwMmon3zYkqM";

WiFiClient wifi;
HttpClient client = HttpClient(wifi, server, port);

void connectWiFi() {
  tft.fillScreen(TFT_BLACK);
  tft.drawString("Connecting WiFi...", 10, 10);

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  tft.fillScreen(TFT_BLACK);
  tft.drawString("WiFi Connected!", 10, 10);
  delay(1000);
}

void setup() {
  Serial.begin(115200);
  delay(2000);

  tft.begin();
  tft.setRotation(3);
  tft.setTextColor(TFT_WHITE);

  connectWiFi();
}

void fetchData() {
  tft.fillScreen(TFT_BLACK);
  tft.setCursor(0, 0);
  tft.println("Fetching...");

  client.beginRequest();
  client.get(endpoint);
  client.sendHeader("Authorization", String("Api-Key ") + apiKey);
  client.endRequest();

  int statusCode = client.responseStatusCode();
  String response = client.responseBody();

  Serial.println("Status: " + String(statusCode));
  Serial.println(response);

  if (statusCode != 200) {
    tft.println("HTTP Error: " + String(statusCode));
    return;
  }

  DynamicJsonDocument doc(4096);
  DeserializationError error = deserializeJson(doc, response);

  if (error) {
    tft.println("JSON Error");
    return;
  }

  tft.fillScreen(TFT_BLACK);
  int y = 0;

  // 📊 Summary
  int pending = doc["pending_count"];
  int stored = doc["stored_count"];
  int occupied = doc["occupied_slots"];
  int total = doc["total_slots"];

  tft.drawString("Pending: " + String(pending), 0, y); y += 20;
  tft.drawString("Stored: " + String(stored), 0, y); y += 20;
  tft.drawString("Slots: " + String(occupied) + "/" + String(total), 0, y); y += 30;

  tft.drawString("ID  Status  Shelf", 0, y); y += 20;

  // 📦 Deliveries
  JsonObject deliveries = doc["deliveries"];

  for (JsonPair kv : deliveries) {
    String id = kv.key().c_str();
    JsonObject d = kv.value();

    String status = d["status"] | "N/A";
    String shelf = d["shelf_id"] | "N/A";

    String line = id + "  " + status + "  " + shelf;

    tft.drawString(line, 0, y);
    y += 20;

    if (y > 220) break;
  }
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();   // auto reconnect
  }

  fetchData();
  delay(10000);
}
