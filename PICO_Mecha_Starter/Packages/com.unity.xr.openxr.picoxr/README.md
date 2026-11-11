This article records the updates in PICO Unity OpenXR SDK v1.4.0.
**Release time**
April 07, 2025
## **Required PICO device system version**
5.13.0 or later
## **What's new**
Below are the updates to this version:
| **Module** | **Feature** | **Description** |
| --- | --- | --- |
| General | / | * Supported Unity 6. <br> * Supported AR Foundation 6. |
| Interaction | [Hand Tracking](/document/unity-openxr/hand-tracking) | * Supported setting the interaction mode using the **Hand Tracking Support** parameter. Below are available options: <br>    * **Controller And Hands**: Automatically switch between controllers and hand poses for user-app interaction. When the user puts down the controllers and the device recognizes hand poses, it uses hand poses for interaction; when the user picks up the controllers, it switches back to controllers for interaction. <br>    * **Hands Only**: Only use hand poses for user-app interaction. <br> * Supported high-frequency hand tracking (60Hz). |
|  | [Body Tracking](/document/unity-openxr/body-tracking) | Added the Body Tracking functionality, which is used to collect information about the user's body position and movements, and convert this information into reproducible pose data. Body Tracking enables users to run, kick, step, lie down, twist the waist, and more, in XR scenes, enriching your app's user experience. |
| Enterprise Service | / | Added a series of APIs, covering device settings, device information retrieval, and more. For more information, refer to this "[API Reference](/reference/unity/client-api/PXR_Enterprise/)". |
**Known issues**

* In PICO device system version 5.13.0, the ray triggered by finger pinch cannot interact with the UI. This issue will be fixed in later versions.
* On PICO devices, images displayed using the Android Surface from the Unity XR Composition Layers Plugin appear mirrored vertically.
*  When displaying images with an alpha value of 0 using the Unity XR Composition Layers Plugin, the composition layers will be rendered abnormally. This issue affects both Overlay and Underlay types of composition layers.
*  Composition layers do not support using multi-view rendering and cubemaps simultaneously.



