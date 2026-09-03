// Crée les deux périphériques audio macOS nécessaires à l'enregistrement.
//
// Seul macOS en a besoin : Linux et Windows exposent déjà de quoi réenregistrer
// leur propre sortie. C'est le point où les trois systèmes divergent le plus.
//
//   Reunion Entree  — périphérique agrégé   : micro + BlackHole  → ce qu'on enregistre
//   Reunion Sortie  — périphérique empilé    : casque + BlackHole → ce qu'on entend
//
// Usage : swift creer-peripheriques.swift [--list] [--mic "<nom>"] [--casque "<nom>"]
//
// Équivalent scripté de « Configuration audio et MIDI », mais sans risque de faute
// de frappe dans les noms (le script d'enregistrement les cherche à l'identique).

import CoreAudio
import Foundation

// MARK: - Lecture des périphériques

func allDevices() -> [AudioDeviceID] {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDevices,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(
        AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size) == noErr else { return [] }
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(
        AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids) == noErr else { return [] }
    return ids
}

func stringProperty(_ id: AudioDeviceID, _ selector: AudioObjectPropertySelector) -> String? {
    var addr = AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var size = UInt32(MemoryLayout<CFString?>.size)
    var value: CFString? = nil
    let status = withUnsafeMutablePointer(to: &value) {
        AudioObjectGetPropertyData(id, &addr, 0, nil, &size, $0)
    }
    guard status == noErr, let str = value else { return nil }
    return str as String
}

/// Nombre de canaux dans une direction donnée : distingue les entrées des sorties,
/// indispensable car micro et casque d'un même casque USB portent le même nom.
func channelCount(_ id: AudioDeviceID, input: Bool) -> Int {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyStreamConfiguration,
        mScope: input ? kAudioDevicePropertyScopeInput : kAudioDevicePropertyScopeOutput,
        mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(id, &addr, 0, nil, &size) == noErr, size > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: 16)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, raw) == noErr else { return 0 }
    let list = raw.assumingMemoryBound(to: AudioBufferList.self)
    return UnsafeMutableAudioBufferListPointer(list).reduce(0) { $0 + Int($1.mNumberChannels) }
}

struct Device {
    let id: AudioDeviceID
    let name: String
    let uid: String
    let inputs: Int
    let outputs: Int
}

func inventory() -> [Device] {
    allDevices().compactMap { id in
        guard let name = stringProperty(id, kAudioObjectPropertyName),
              let uid = stringProperty(id, kAudioDevicePropertyDeviceUID) else { return nil }
        return Device(id: id, name: name, uid: uid,
                      inputs: channelCount(id, input: true),
                      outputs: channelCount(id, input: false))
    }
}

func find(_ devices: [Device], named name: String, input: Bool) -> Device? {
    let wanted = name.lowercased()
    let matching = devices.filter { input ? $0.inputs > 0 : $0.outputs > 0 }
    return matching.first { $0.name.lowercased() == wanted }
        ?? matching.first { $0.name.lowercased().contains(wanted) }
}

// MARK: - Création

func destroyIfExists(uid: String) {
    if let existing = inventory().first(where: { $0.uid == uid }) {
        AudioHardwareDestroyAggregateDevice(existing.id)
    }
}

/// `stacked: true` produit un « périphérique de sortie multiple », `false` un « périphérique agrégé ».
@discardableResult
func createAggregate(name: String, uid: String, master: Device, extra: Device, stacked: Bool) -> Bool {
    destroyIfExists(uid: uid)

    let subDevices: [[String: Any]] = [
        [kAudioSubDeviceUIDKey: master.uid,
         kAudioSubDeviceDriftCompensationKey: 0],
        // Correction de dérive sur BlackHole : son horloge est logicielle et
        // dérive de celle du périphérique physique — sans ça, l'audio se désynchronise.
        [kAudioSubDeviceUIDKey: extra.uid,
         kAudioSubDeviceDriftCompensationKey: 1],
    ]

    let description: [String: Any] = [
        kAudioAggregateDeviceNameKey: name,
        kAudioAggregateDeviceUIDKey: uid,
        kAudioAggregateDeviceSubDeviceListKey: subDevices,
        kAudioAggregateDeviceMasterSubDeviceKey: master.uid,
        kAudioAggregateDeviceIsPrivateKey: 0,   // 0 = persistant, visible partout
        kAudioAggregateDeviceIsStackedKey: stacked ? 1 : 0,
    ]

    var newID = AudioDeviceID(0)
    let status = AudioHardwareCreateAggregateDevice(description as CFDictionary, &newID)
    if status != noErr {
        FileHandle.standardError.write("❌ Échec création « \(name) » (OSStatus \(status))\n".data(using: .utf8)!)
        return false
    }
    print("✅ « \(name) » créé — \(master.name) + \(extra.name)")
    return true
}

// MARK: - Sortie audio par défaut

func defaultOutputID() -> AudioDeviceID {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultOutputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var id = AudioDeviceID(0)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &id)
    return id
}

// Le gain d'entrée d'un micro. Un micro réglé bas donne un signal que la
// transcription n'entend pas : mesuré à -43 dB sur un poste réel, le modèle
// inventait des phrases au lieu de rendre celles prononcées.
func inputGain(_ id: AudioDeviceID) -> Float? {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyVolumeScalar,
        mScope: kAudioDevicePropertyScopeInput,
        mElement: kAudioObjectPropertyElementMain)
    var valeur: Float = 0
    var size = UInt32(MemoryLayout<Float>.size)
    if AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &valeur) == noErr { return valeur }
    // Certains périphériques n'exposent le volume que canal par canal.
    addr.mElement = 1
    if AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &valeur) == noErr { return valeur }
    return nil
}

func setInputGain(_ id: AudioDeviceID, _ valeur: Float) -> Bool {
    var reglee = max(0, min(1, valeur))
    let size = UInt32(MemoryLayout<Float>.size)
    for element in [kAudioObjectPropertyElementMain, 1, 2] {
        var addr = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyVolumeScalar,
            mScope: kAudioDevicePropertyScopeInput,
            mElement: AudioObjectPropertyElement(element))
        var reglable = DarwinBoolean(false)
        if AudioObjectIsPropertySettable(id, &addr, &reglable) == noErr, reglable.boolValue,
           AudioObjectSetPropertyData(id, &addr, 0, nil, size, &reglee) == noErr {
            return true
        }
    }
    return false
}

func setDefaultInput(_ id: AudioDeviceID) -> Bool {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultInputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var value = id
    let size = UInt32(MemoryLayout<AudioDeviceID>.size)
    return AudioObjectSetPropertyData(
        AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, size, &value) == noErr
}

func setDefaultOutput(_ id: AudioDeviceID) -> Bool {
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultOutputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    var value = id
    let size = UInt32(MemoryLayout<AudioDeviceID>.size)
    return AudioObjectSetPropertyData(
        AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, size, &value) == noErr
}

// MARK: - Programme

let args = CommandLine.arguments
func option(_ flag: String, _ fallback: String) -> String {
    guard let i = args.firstIndex(of: flag), i + 1 < args.count else { return fallback }
    return args[i + 1]
}

let devices = inventory()

if args.contains("--list") {
    print("Périphériques audio :\n")
    for d in devices.sorted(by: { $0.name < $1.name }) {
        var roles: [String] = []
        if d.inputs > 0 { roles.append("entrée \(d.inputs)ch") }
        if d.outputs > 0 { roles.append("sortie \(d.outputs)ch") }
        print("  \(d.name)  [\(roles.joined(separator: ", "))]\n    uid: \(d.uid)")
    }
    exit(0)
}

// Bascule de la sortie système, utilisée par rec-reunion.sh au début et à la fin
// de l'enregistrement pour que ce ne soit pas à retenir avant chaque réunion.
if args.contains("--get-output") {
    print(stringProperty(defaultOutputID(), kAudioObjectPropertyName) ?? "")
    exit(0)
}

if let i = args.firstIndex(of: "--set-output"), i + 1 < args.count {
    let target = args[i + 1]
    guard let device = find(devices, named: target, input: false) else {
        FileHandle.standardError.write("❌ Sortie « \(target) » introuvable\n".data(using: .utf8)!)
        exit(1)
    }
    exit(setDefaultOutput(device.id) ? 0 : 1)
}

if let i = args.firstIndex(of: "--set-input"), i + 1 < args.count {
    let cible = args[i + 1]
    guard let device = find(devices, named: cible, input: true) else {
        FileHandle.standardError.write("❌ Entrée « \(cible) » introuvable\n".data(using: .utf8)!)
        exit(1)
    }
    exit(setDefaultInput(device.id) ? 0 : 1)
}

// Lecture et réglage du gain d'entrée, pour que l'outil corrige de lui-même un
// micro laissé trop bas plutôt que de rendre une transcription inventée.
if let i = args.firstIndex(of: "--get-gain"), i + 1 < args.count {
    guard let device = find(devices, named: args[i + 1], input: true),
          let gain = inputGain(device.id) else { exit(1) }
    print(String(format: "%.3f", gain))
    exit(0)
}

if let i = args.firstIndex(of: "--set-gain"), i + 2 < args.count {
    guard let device = find(devices, named: args[i + 1], input: true),
          let valeur = Float(args[i + 2]) else { exit(1) }
    exit(setInputGain(device.id, valeur) ? 0 : 1)
}

let micName = option("--mic", "Jabra EVOLVE 30 II")
let casqueName = option("--casque", "Jabra EVOLVE 30 II")

guard let blackholeIn = find(devices, named: "BlackHole", input: true),
      let blackholeOut = find(devices, named: "BlackHole", input: false) else {
    FileHandle.standardError.write("""
    ❌ BlackHole est introuvable côté CoreAudio.
       Le driver est installé mais le démon audio ne l'a pas chargé. Lance :
           sudo killall coreaudiod

    """.data(using: .utf8)!)
    exit(1)
}

guard let mic = find(devices, named: micName, input: true) else {
    FileHandle.standardError.write("❌ Micro « \(micName) » introuvable. Voir --list\n".data(using: .utf8)!)
    exit(1)
}
guard let casque = find(devices, named: casqueName, input: false) else {
    FileHandle.standardError.write("❌ Sortie « \(casqueName) » introuvable. Voir --list\n".data(using: .utf8)!)
    exit(1)
}

let entree = createAggregate(name: "Reunion Entree", uid: "com.reunions.entree",
                             master: mic, extra: blackholeIn, stacked: false)
let sortie = createAggregate(name: "Reunion Sortie", uid: "com.reunions.sortie",
                             master: casque, extra: blackholeOut, stacked: true)

exit(entree && sortie ? 0 : 1)
